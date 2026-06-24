from __future__ import annotations

import json
import re
from typing import Any

from app.policy import AdminPolicy
from app.redaction import RedactionPolicy, redact_payload
from core.events import CanonicalEvent
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from storage.repositories import DebugTraceRecord
from storage.unit_of_work import RepositoryBundle


DEBUG_LEVELS = (0, 1, 2)
MAX_DEBUG_EVENTS_BY_LEVEL = {
    0: 0,
    1: 40,
    2: 160,
}
DEBUG_MESSAGE_CHARS = 1800
DEBUG_REDACTION_POLICY_BY_LEVEL = {
    0: RedactionPolicy(max_string_length=120, max_sequence_items=8, max_mapping_items=20, max_depth=3),
    1: RedactionPolicy(max_string_length=240, max_sequence_items=20, max_mapping_items=40, max_depth=5),
    2: RedactionPolicy(max_string_length=1200, max_sequence_items=80, max_mapping_items=120, max_depth=8),
}


class DebugWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        admin_policy: AdminPolicy,
        current_trace_id: str,
    ) -> WorkflowResult:
        level = debug_level_from_options(event.metadata.get("options", {}), default=0)
        latest = (
            repositories.debug_traces.latest(exclude_trace_id=current_trace_id)
            if admin_policy.is_admin(event.user_id)
            else repositories.debug_traces.latest_for_user(event.user_id, exclude_trace_id=current_trace_id)
        )
        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=debug_messages_for_trace(repositories, latest, level=level, ephemeral=True),
        )


def debug_level_from_options(options: object, *, default: int = 0) -> int:
    if not isinstance(options, dict):
        return default
    value = options.get("level", default)
    try:
        level = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return level if level in DEBUG_LEVELS else default


def debug_level_from_text(text: str) -> int | None:
    matches = tuple(re.finditer(r"(?<!\w)\+debug([012])\b", text, flags=re.IGNORECASE))
    if not matches:
        return None
    return int(matches[-1].group(1))


def strip_debug_modifiers(text: str) -> str:
    return " ".join(re.sub(r"(?<!\w)\+debug[012]\b", " ", text, flags=re.IGNORECASE).split())


def debug_messages_for_trace(
    repositories: RepositoryBundle,
    trace: DebugTraceRecord | None,
    *,
    level: int,
    ephemeral: bool,
) -> tuple[OutgoingMessage, ...]:
    normalized_level = level if level in DEBUG_LEVELS else 0
    payload = debug_payload_for_trace(repositories, trace, level=normalized_level)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    kind = OutgoingKind.EPHEMERAL_TEXT if ephemeral else OutgoingKind.TEXT
    chunks = _debug_chunks(content)
    return tuple(
        OutgoingMessage(
            kind=kind,
            text=chunk,
            metadata={
                "debug_level": normalized_level,
                "debug_chunk_index": index + 1,
                "debug_chunk_count": len(chunks),
            },
        )
        for index, chunk in enumerate(chunks)
    )


def debug_payload_for_trace(repositories: RepositoryBundle, trace: DebugTraceRecord | None, *, level: int) -> dict[str, Any]:
    if trace is None:
        return {"debug_level": level, "debug_trace": None}

    events = repositories.debug_traces.list_events(trace.trace_id)
    max_events = MAX_DEBUG_EVENTS_BY_LEVEL[level]
    returned_events = events[:max_events] if max_events else ()
    redaction_policy = DEBUG_REDACTION_POLICY_BY_LEVEL[level]
    summary = {
        "trace_id": trace.trace_id,
        "source_event_id": trace.source_event_id,
        "workflow": trace.workflow,
        "status": trace.status,
        "started_at": trace.started_at,
        "finished_at": trace.finished_at,
        "event_count": len(events),
        "stage_counts": _stage_counts(events),
        "llm_calls": _llm_call_summary(events),
        "errors": _error_summary(events),
    }
    debug_trace: dict[str, Any] = dict(summary)
    if level >= 1:
        debug_trace.update(
            {
                "payload": redact_payload(trace.payload, redaction_policy),
                "events_returned": len(returned_events),
                "events_truncated": max(0, len(events) - len(returned_events)),
                "events": [
                    {
                        "trace_event_id": event.trace_event_id,
                        "stage": event.stage,
                        "level": event.level,
                        "message": event.message,
                        "payload": _event_payload_for_level(event.payload, level=level, redaction_policy=redaction_policy),
                        "created_at": event.created_at,
                    }
                    for event in returned_events
                ],
            }
        )
    return {"debug_level": level, "debug_trace": debug_trace}


def _event_payload_for_level(payload: dict[str, Any], *, level: int, redaction_policy: RedactionPolicy) -> dict[str, Any]:
    redacted = redact_payload(payload, redaction_policy)
    if level >= 2:
        return redacted
    if isinstance(redacted, dict) and "llm_payloads" in redacted:
        redacted = dict(redacted)
        redacted["llm_payloads"] = "[available at debug level 2]"
    return redacted


def _stage_counts(events) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.stage] = counts.get(event.stage, 0) + 1
    return counts


def _llm_call_summary(events) -> list[dict[str, Any]]:
    calls = []
    for event in events:
        if event.stage != "llm":
            continue
        payload = event.payload
        calls.append(
            {
                "operation": payload.get("operation", event.message),
                "status": payload.get("status", event.level),
                "duration_ms": payload.get("duration_ms"),
                "response_keys": payload.get("response_keys", ()),
                "error_type": payload.get("error_type", ""),
            }
        )
    return calls


def _error_summary(events) -> list[dict[str, Any]]:
    errors = []
    for event in events:
        if event.level not in {"warning", "error"}:
            continue
        errors.append(
            {
                "stage": event.stage,
                "level": event.level,
                "message": event.message,
                "error_type": event.payload.get("error_type", ""),
                "error_category": event.payload.get("error_category", ""),
            }
        )
    return errors


def _debug_chunks(content: str) -> tuple[str, ...]:
    if len(content) <= DEBUG_MESSAGE_CHARS:
        return (content,)
    chunks = []
    for index in range(0, len(content), DEBUG_MESSAGE_CHARS):
        chunks.append(content[index : index + DEBUG_MESSAGE_CHARS])
    total = len(chunks)
    return tuple(f"Aimo debug {index + 1}/{total}\n{chunk}" for index, chunk in enumerate(chunks))
