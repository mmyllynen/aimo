from __future__ import annotations

from core.events import AttachmentRef, CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
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
    ) -> WorkflowResult:
        attachment = _first_supported_attachment(event.attachments)
        if attachment is None:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.UNSUPPORTED_ATTACHMENT,
                TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
                "No supported GPX attachment found",
            )
        content = attachment.metadata.get("content")
        if not isinstance(content, bytes):
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.UNSUPPORTED_ATTACHMENT,
                TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
                "Attachment content is not available in this runtime boundary",
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
                ),
                repositories,
            )
        except UnsupportedAttachmentError as exc:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.UNSUPPORTED_ATTACHMENT,
                TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT,
                str(exc),
            )
        except InvalidGpxError as exc:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.INVALID_GPX,
                TranslationKey.GPX_REJECTED,
                str(exc),
            )

        if result.workout is None:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.INVALID_GPX,
                TranslationKey.GPX_REJECTED,
                "Duplicate attachment did not resolve to a workout",
            )

        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.TEXT,
                    localized_text=LocalizedText(
                        key=TranslationKey.GPX_DUPLICATE if result.duplicate else TranslationKey.GPX_ACCEPTED,
                        params={"title": result.workout.title},
                    ),
                    metadata={
                        "workout_id": result.workout.workout_id,
                        "duplicate": result.duplicate,
                    },
                ),
            ),
        )


def _first_supported_attachment(attachments: tuple[AttachmentRef, ...]) -> AttachmentRef | None:
    for attachment in attachments:
        if is_supported_gpx_attachment(attachment.filename, attachment.content_type):
            return attachment
    return None


def _error_result(
    status: WorkflowStatus,
    category: ErrorCategory,
    message_key: TranslationKey,
    message: str,
) -> WorkflowResult:
    return WorkflowResult(
        status=status,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=message_key),
            ),
        ),
        error=AppError(
            category=category,
            message=message,
            user_message_key=message_key.value,
        ),
    )
