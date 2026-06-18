from __future__ import annotations

import re

from core.events import AttachmentRef, CanonicalEvent
from core.events import EventKind
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import GpxTitleInput, extract_gpx_title
from pathlib import Path
from storage.unit_of_work import RepositoryBundle
from workout.ingest import (
    GpxIngestRequest,
    InvalidGpxError,
    UnsupportedAttachmentError,
    ingest_gpx,
    is_supported_gpx_attachment,
)


class GpxIngestWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        max_attachment_size_bytes: int,
        raw_storage_root: Path | None = None,
        gateway: LLMGateway | None = None,
    ) -> WorkflowResult:
        attachments = _supported_attachments(event.attachments)
        if not attachments:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.UNSUPPORTED_ATTACHMENT,
                TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
                "No supported GPX attachment found",
            )

        messages: list[OutgoingMessage] = []
        errors: list[AppError] = []
        success_count = 0
        title_override = _title_override(event, attachments, gateway=gateway)
        for attachment in attachments:
            result = _handle_attachment(
                attachment,
                event,
                repositories,
                max_attachment_size_bytes=max_attachment_size_bytes,
                raw_storage_root=raw_storage_root,
                title_override=title_override,
            )
            messages.extend(result.messages)
            if result.error is not None:
                errors.append(result.error)
            if result.ok:
                success_count += 1

        if success_count:
            return WorkflowResult(status=WorkflowStatus.SUCCESS, messages=tuple(messages))

        return WorkflowResult(
            status=WorkflowStatus.USER_ERROR,
            messages=tuple(messages),
            error=errors[0] if errors else None,
        )


def _handle_attachment(
    attachment: AttachmentRef,
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    *,
    max_attachment_size_bytes: int,
    raw_storage_root: Path | None,
    title_override: str = "",
) -> WorkflowResult:
    content = attachment.metadata.get("content")
    if not isinstance(content, bytes):
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.UNSUPPORTED_ATTACHMENT,
            TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
            "Attachment content is not available in this runtime boundary",
            filename=attachment.filename,
        )

    try:
        result = ingest_gpx(
            GpxIngestRequest(
                owner_user_id=event.user_id,
                guild_id=event.guild_id,
                channel_id=event.channel_id,
                message_id=event.event_id,
                attachment_id=attachment.attachment_id,
                filename=attachment.filename,
                content_type=attachment.content_type,
                content=content,
                created_at=event.created_at,
                max_size_bytes=max_attachment_size_bytes,
                raw_storage_root=raw_storage_root,
                title_override=title_override,
            ),
            repositories,
        )
    except UnsupportedAttachmentError as exc:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.UNSUPPORTED_ATTACHMENT,
            TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
            str(exc),
            filename=attachment.filename,
        )
    except InvalidGpxError as exc:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.INVALID_GPX,
            TranslationKey.GPX_REJECTED,
            str(exc),
            filename=attachment.filename,
        )

    if result.workout is None:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.INVALID_GPX,
            TranslationKey.GPX_REJECTED,
            "Duplicate attachment did not resolve to a workout",
            filename=attachment.filename,
        )

    return WorkflowResult(
        status=WorkflowStatus.SUCCESS,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(
                    key=_success_message_key(result.workout, duplicate=result.duplicate),
                    params={"filename": attachment.filename, "title": result.workout.title},
                ),
                metadata={
                    "workout_id": result.workout.workout_id,
                    "duplicate": result.duplicate,
                },
            ),
        ),
    )


def _success_message_key(workout, *, duplicate: bool) -> TranslationKey:
    is_route = workout.primary_kind == "route" or workout.kind == "route_plan"
    if duplicate:
        return TranslationKey.GPX_DUPLICATE_ROUTE if is_route else TranslationKey.GPX_DUPLICATE
    return TranslationKey.GPX_ACCEPTED_ROUTE if is_route else TranslationKey.GPX_ACCEPTED


def _supported_attachments(attachments: tuple[AttachmentRef, ...]) -> tuple[AttachmentRef, ...]:
    return tuple(
        attachment
        for attachment in attachments
        if is_supported_gpx_attachment(attachment.filename, attachment.content_type)
    )


def _title_override(
    event: CanonicalEvent,
    attachments: tuple[AttachmentRef, ...],
    *,
    gateway: LLMGateway | None,
) -> str:
    command_name = str(event.metadata.get("command_name", "")).strip().lower()
    subcommand = str(event.metadata.get("subcommand", "")).strip().lower()
    if event.kind == EventKind.SLASH_COMMAND and command_name == "gpx" and subcommand == "tallenna" and len(attachments) == 1:
        options = event.metadata.get("options", {})
        if isinstance(options, dict):
            return _clean_title(str(options.get("nimi", "")))
        return ""
    if event.kind != EventKind.MENTION or len(attachments) != 1:
        return ""
    if title := _title_tarkenne(event.text):
        return title
    if gateway is None:
        return ""
    try:
        return _clean_title(
            extract_gpx_title(
                gateway,
                GpxTitleInput(
                    user_text=event.text,
                    attachment_count=len(attachments),
                ),
            ).title
        )
    except LLMGatewayError:
        return ""


def _title_tarkenne(text: str) -> str:
    for key in ("nimi", "name"):
        pattern = rf"(?<!\w){key}\s*=\s*(\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s;]+)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is not None:
            return _clean_title(_unquote_tarkenne_value(match.group(1)))
    return ""


def _unquote_tarkenne_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].replace(f"\\{value[0]}", value[0]).replace("\\\\", "\\")
    return value


def _clean_title(value: str) -> str:
    return " ".join(value.split())[:120]


def _error_result(
    status: WorkflowStatus,
    category: ErrorCategory,
    message_key: TranslationKey,
    message: str,
    *,
    filename: str = "",
) -> WorkflowResult:
    return WorkflowResult(
        status=status,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=message_key, params={"filename": filename}),
            ),
        ),
        error=AppError(
            category=category,
            message=message,
            user_message_key=message_key.value,
        ),
    )
