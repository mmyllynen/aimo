from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from app.policy import AdminPolicy
from app.redaction import redact_payload
from core.config import MapsConfig, RenderersConfig
from core.events import CanonicalEvent, EventKind
from core.errors import AppError, ErrorCategory
from core.i18n import DEFAULT_LANGUAGE, LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteConfidence, RouteDecision, WorkflowTarget
from core.trace import TraceLevel, TraceStage
from core.workflows import OutgoingKind, OutgoingMessage, StateUpdate, WorkflowResult, WorkflowStatus
from llm.gateway import LLMCallTrace, LLMGateway, LLMGatewayError
from llm.operations import IntentClassificationInput, classify_intent
from storage.repositories import DebugTraceEventRecord, HistoryEventRecord
from storage.unit_of_work import RepositoryBundle, UnitOfWork
from workflows.chat import ChatWorkflow
from workflows.debug import DebugWorkflow
from workflows.gpx_ingest import GpxIngestWorkflow
from workflows.help import HelpWorkflow
from workflows.noop import NoopWorkflow
from workflows.visualization import VisualizationWorkflow
from workflows.workout_chat import WorkoutChatWorkflow
from workflows.workout_management import WorkoutManagementWorkflow


@dataclass(frozen=True)
class DispatchContext:
    unit_of_work: UnitOfWork
    admin_policy: AdminPolicy = AdminPolicy()
    language: SupportedLanguage = DEFAULT_LANGUAGE
    llm_gateway: LLMGateway | None = None
    max_attachment_size_bytes: int = 25 * 1024 * 1024
    raw_gpx_path: Path | None = None
    artifact_path: Path | None = None
    maps_config: MapsConfig = MapsConfig()
    renderers_config: RenderersConfig = RenderersConfig()
    status_callback: Callable[[str], None] | None = None
    trace_keep_limit: int = 1000


class Dispatcher:
    def __init__(
        self,
        *,
        help_workflow: HelpWorkflow | None = None,
        debug_workflow: DebugWorkflow | None = None,
        noop_workflow: NoopWorkflow | None = None,
        chat_workflow: ChatWorkflow | None = None,
        gpx_ingest_workflow: GpxIngestWorkflow | None = None,
        visualization_workflow: VisualizationWorkflow | None = None,
        workout_chat_workflow: WorkoutChatWorkflow | None = None,
        workout_management_workflow: WorkoutManagementWorkflow | None = None,
    ) -> None:
        self.help_workflow = help_workflow or HelpWorkflow()
        self.debug_workflow = debug_workflow or DebugWorkflow()
        self.noop_workflow = noop_workflow or NoopWorkflow()
        self.chat_workflow = chat_workflow or ChatWorkflow()
        self.gpx_ingest_workflow = gpx_ingest_workflow or GpxIngestWorkflow()
        self.visualization_workflow = visualization_workflow or VisualizationWorkflow()
        self.workout_chat_workflow = workout_chat_workflow or WorkoutChatWorkflow()
        self.workout_management_workflow = workout_management_workflow or WorkoutManagementWorkflow()

    def dispatch(self, event: CanonicalEvent, context: DispatchContext) -> WorkflowResult:
        with context.unit_of_work as repositories:
            existing_user = repositories.users.get(event.user_id)
            user_metadata, first_interaction_payload = _user_metadata_for_event(
                existing_user.metadata if existing_user is not None else {},
                event,
            )
            repositories.users.touch(
                user_id=event.user_id,
                discord_user_name=event.user_name,
                discord_display_name=str(event.metadata.get("discord_display_name", "")),
                seen_at=event.created_at,
                source=event.source.value,
                metadata=user_metadata,
            )
            repositories.channels.upsert(
                channel_id=event.channel_id,
                guild_id=event.guild_id,
            )
            repositories.history.add(_history_record(event))

            try:
                route = route_event(event, llm_gateway=context.llm_gateway)
            except LLMGatewayError:
                return _routing_model_unavailable_result(event, repositories, context)
            trace_id = _trace_id(event)
            repositories.debug_traces.create(
                trace_id=trace_id,
                source_event_id=event.event_id,
                workflow=route.target.value,
                status="started",
                started_at=event.created_at,
                payload={
                    "user_id": event.user_id,
                    "channel_id": event.channel_id,
                    "guild_id": event.guild_id,
                    "route_confidence": route.confidence.value,
                },
            )
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.INBOUND,
                level=TraceLevel.INFO,
                message="Inbound canonical event accepted.",
                payload={
                    "event_kind": event.kind.value,
                    "source": event.source.value,
                    "text_chars": len(event.text),
                    "attachment_count": len(event.attachments),
                    "metadata_keys": sorted(str(key) for key in event.metadata.keys()),
                },
                created_at=event.created_at.isoformat(),
            )
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.REPOSITORY,
                level=TraceLevel.INFO,
                message="Inbound user, channel, and history records persisted.",
                payload={
                    "operations": ("users.touch", "channels.upsert", "history.add"),
                    "history_id": event.event_id,
                },
                created_at=event.created_at.isoformat(),
            )
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.ROUTE,
                level=TraceLevel.INFO,
                message=route.reason,
                payload={
                    "target": route.target.value,
                    "confidence": route.confidence.value,
                    "slots": route.slots,
                },
                created_at=event.created_at.isoformat(),
            )
            llm_gateway = _trace_llm_gateway(context.llm_gateway, repositories.debug_traces, trace_id, event)
            workflow_repositories = _trace_repository_bundle(
                repositories,
                debug_traces=repositories.debug_traces,
                trace_id=trace_id,
                created_at=event.created_at.isoformat(),
            )

            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.WORKFLOW,
                level=TraceLevel.INFO,
                message="Workflow started.",
                payload={"workflow": route.target.value},
                created_at=event.created_at.isoformat(),
            )
            if route.target == WorkflowTarget.HELP:
                result = self.help_workflow.handle(event, route)
            elif route.target == WorkflowTarget.DEBUG:
                result = self.debug_workflow.handle(
                    event,
                    route,
                    workflow_repositories,
                    admin_policy=context.admin_policy,
                    current_trace_id=trace_id,
                )
            elif route.target == WorkflowTarget.WORKOUT_MANAGEMENT:
                result = self.workout_management_workflow.handle(event, route, workflow_repositories)
            elif route.target == WorkflowTarget.GPX_INGEST:
                result = self.gpx_ingest_workflow.handle(
                    event,
                    route,
                    workflow_repositories,
                    max_attachment_size_bytes=context.max_attachment_size_bytes,
                    raw_storage_root=context.raw_gpx_path,
                )
            elif route.target == WorkflowTarget.VISUALIZATION:
                if context.status_callback is not None:
                    context.status_callback("visualization_started")
                result = self.visualization_workflow.handle(
                    event,
                    route,
                    workflow_repositories,
                    gateway=llm_gateway,
                    language=context.language,
                    artifact_root=context.artifact_path,
                    maps_config=context.maps_config,
                    renderers_config=context.renderers_config,
                )
            elif route.target == WorkflowTarget.WORKOUT_CHAT:
                result = self.workout_chat_workflow.handle(
                    event,
                    route,
                    workflow_repositories,
                    gateway=llm_gateway,
                    language=context.language,
                )
            elif route.target == WorkflowTarget.CHAT:
                result = self.chat_workflow.handle(
                    event,
                    route,
                    workflow_repositories,
                    gateway=llm_gateway,
                    language=context.language,
                )
            else:
                result = self.noop_workflow.handle(event, route)
            if first_interaction_payload is not None:
                result = _with_state_update(
                    result,
                    StateUpdate(
                        namespace="users",
                        operation="first_interaction",
                        payload=first_interaction_payload,
                    ),
                )

            _add_workflow_trace_events(repositories.debug_traces, trace_id, result)
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.WORKFLOW,
                level=TraceLevel.INFO if result.error is None else TraceLevel.WARNING,
                message="Workflow finished.",
                payload={
                    "workflow": route.target.value,
                    "status": result.status.value,
                    "error_category": result.error.category.value if result.error is not None else None,
                },
                created_at=event.created_at.isoformat(),
            )
            if route.target == WorkflowTarget.VISUALIZATION:
                _add_render_trace_event(repositories.debug_traces, trace_id, result, event)
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.OUTBOUND,
                level=TraceLevel.INFO,
                message="Outbound response prepared.",
                payload=_outbound_payload(result),
                created_at=event.created_at.isoformat(),
            )
            repositories.debug_traces.finish(
                trace_id,
                status=result.status.value,
                finished_at=event.created_at,
            )
            _add_trace_event(
                repositories.debug_traces,
                trace_id=trace_id,
                stage=TraceStage.RESULT,
                level=TraceLevel.INFO,
                message=result.status.value,
                payload={
                    "message_count": len(result.messages),
                    "state_update_count": len(result.state_updates),
                    "has_error": result.error is not None,
                },
                created_at=event.created_at.isoformat(),
            )
            repositories.debug_traces.prune_to_limit(keep=context.trace_keep_limit)
            return result


def route_event(event: CanonicalEvent, *, llm_gateway: LLMGateway | None = None) -> RouteDecision:
    if event.kind == EventKind.MESSAGE:
        return RouteDecision(
            target=WorkflowTarget.CHAT,
            confidence=RouteConfidence.LOW,
            reason="Normal non-mention message is stored but not handled.",
        )

    command_name = str(event.metadata.get("command_name", "")).lower()
    text = event.text.strip().lower()
    if command_name == "debug" or text in {"/debug", "debug"}:
        return RouteDecision(
            target=WorkflowTarget.DEBUG,
            confidence=RouteConfidence.HIGH,
            reason="Explicit debug command.",
        )
    if command_name == "treenit":
        options = event.metadata.get("options", {})
        return RouteDecision(
            target=WorkflowTarget.WORKOUT_MANAGEMENT,
            confidence=RouteConfidence.HIGH,
            slots={
                "command": command_name,
                "options": options if isinstance(options, dict) else {},
            },
            reason="Explicit workout management command.",
        )
    if _is_help_request(event):
        return RouteDecision(
            target=WorkflowTarget.HELP,
            confidence=RouteConfidence.HIGH,
            reason="Explicit help request.",
        )
    if command_name in {"visualisointi", "visualization"}:
        return RouteDecision(
            target=WorkflowTarget.VISUALIZATION,
            confidence=RouteConfidence.HIGH,
            reason="Explicit visualization command.",
        )
    if event.attachments and _has_gpx_attachment(event):
        return RouteDecision(
            target=WorkflowTarget.GPX_INGEST,
            confidence=RouteConfidence.HIGH,
            slots={
                "attachment_ids": [attachment.attachment_id for attachment in event.attachments],
            },
            reason="Supported GPX attachment present.",
        )
    if event.attachments and _has_image_attachment(event) and _should_use_llm_routing(event, command_name, llm_gateway):
        return classify_intent(
            llm_gateway,
            IntentClassificationInput(
                event_kind=event.kind.value,
                user_text=event.text,
                has_attachments=True,
                compact_channel_state={
                    "guild_id_present": event.guild_id is not None,
                    "source": event.source.value,
                    "command_name": command_name,
                    "has_image_attachment": True,
                },
            )
        )
    if event.attachments:
        return RouteDecision(
            target=WorkflowTarget.GPX_INGEST,
            confidence=RouteConfidence.HIGH,
            slots={
                "attachment_ids": [attachment.attachment_id for attachment in event.attachments],
                "unsupported_attachment": True,
            },
            reason="Attachment present but no supported GPX attachment found.",
        )
    if _should_use_llm_routing(event, command_name, llm_gateway):
        return classify_intent(
            llm_gateway,
            IntentClassificationInput(
                event_kind=event.kind.value,
                user_text=event.text,
                has_attachments=bool(event.attachments),
                compact_channel_state={
                    "guild_id_present": event.guild_id is not None,
                    "source": event.source.value,
                    "command_name": command_name,
                },
            )
        )
    return RouteDecision(
        target=WorkflowTarget.CHAT,
        confidence=RouteConfidence.LOW,
        reason="No deterministic skeleton route matched.",
    )


def _user_metadata_for_event(
    existing_metadata: dict[str, Any],
    event: CanonicalEvent,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    metadata = dict(existing_metadata)
    created_at = event.created_at.isoformat()
    metadata.setdefault("first_observed_at", created_at)
    is_interaction = event.kind in {EventKind.MENTION, EventKind.SLASH_COMMAND, EventKind.COMPONENT}
    if not is_interaction:
        metadata.setdefault("interaction_state", "observed")
        return metadata, None

    if metadata.get("interaction_state") == "interacted":
        return metadata, None

    metadata["interaction_state"] = "interacted"
    metadata.setdefault("first_interacted_at", created_at)
    metadata.setdefault("first_interaction_kind", event.kind.value)
    metadata.setdefault("first_interaction_source", event.source.value)
    command_name = str(event.metadata.get("command_name", ""))
    if command_name:
        metadata.setdefault("first_interaction_command", command_name)
    payload = {
        "user_id": event.user_id,
        "user_name": event.user_name,
        "discord_display_name": str(event.metadata.get("discord_display_name", "")),
        "guild_id": event.guild_id,
        "channel_id": event.channel_id,
        "event_id": event.event_id,
        "interaction_kind": event.kind.value,
        "source": event.source.value,
        "command_name": command_name,
        "created_at": created_at,
    }
    return metadata, payload


def _with_state_update(result: WorkflowResult, update: StateUpdate) -> WorkflowResult:
    return WorkflowResult(
        status=result.status,
        messages=result.messages,
        state_updates=(*result.state_updates, update),
        trace_events=result.trace_events,
        error=result.error,
    )


def _routing_model_unavailable_result(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    context: DispatchContext,
) -> WorkflowResult:
    del context
    trace_id = _trace_id(event)
    repositories.debug_traces.create(
        trace_id=trace_id,
        source_event_id=event.event_id,
        workflow=WorkflowTarget.CHAT.value,
        status=WorkflowStatus.SYSTEM_ERROR.value,
        started_at=event.created_at,
        payload={
            "user_id": event.user_id,
            "channel_id": event.channel_id,
            "guild_id": event.guild_id,
            "route_confidence": RouteConfidence.LOW.value,
        },
    )
    _add_trace_event(
        repositories.debug_traces,
        trace_id=trace_id,
        stage=TraceStage.ROUTE,
        level=TraceLevel.ERROR,
        message="LLM routing failed.",
        payload={"error_category": ErrorCategory.MODEL_UNAVAILABLE.value},
        created_at=event.created_at.isoformat(),
    )
    repositories.debug_traces.finish(
        trace_id,
        status=WorkflowStatus.SYSTEM_ERROR.value,
        finished_at=event.created_at,
    )
    return WorkflowResult(
        status=WorkflowStatus.SYSTEM_ERROR,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=TranslationKey.ERROR_MODEL_UNAVAILABLE),
            ),
        ),
        error=AppError(
            category=ErrorCategory.MODEL_UNAVAILABLE,
            message="LLM routing failed",
            user_message_key=TranslationKey.ERROR_MODEL_UNAVAILABLE.value,
        ),
    )


def _is_help_request(event: CanonicalEvent) -> bool:
    command_name = str(event.metadata.get("command_name", "")).lower()
    options = event.metadata.get("options", {})
    text = event.text.strip().lower()
    if command_name == "aimo" and text in {"", "aimo", "/aimo"}:
        return not _has_useful_options(options)
    return command_name in {"help"} or text in {"apua", "help", "/help", "/aimo"}


def _has_useful_options(options: object) -> bool:
    if not isinstance(options, dict):
        return False
    return any(value not in (None, "", False) for value in options.values())


def _should_use_llm_routing(
    event: CanonicalEvent,
    command_name: str,
    llm_gateway: LLMGateway | None,
) -> bool:
    if llm_gateway is None:
        return False
    if event.kind == EventKind.MENTION:
        return True
    if event.kind == EventKind.SLASH_COMMAND and command_name == "aimo" and event.text.strip():
        return True
    return False


def _has_gpx_attachment(event: CanonicalEvent) -> bool:
    return any(
        attachment.filename.lower().endswith(".gpx")
        or attachment.content_type.strip().lower() in {"application/gpx+xml", "application/xml", "text/xml"}
        for attachment in event.attachments
    )


def _has_image_attachment(event: CanonicalEvent) -> bool:
    return any(
        (
            attachment.filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            or attachment.content_type.split(";", 1)[0].strip().lower() in {"image/jpeg", "image/png", "image/webp"}
        )
        and (bool(attachment.url) or isinstance(attachment.metadata.get("content"), bytes))
        for attachment in event.attachments
    )


def _history_record(event: CanonicalEvent) -> HistoryEventRecord:
    return HistoryEventRecord(
        history_id=event.event_id,
        guild_id=event.guild_id,
        channel_id=event.channel_id,
        user_id=event.user_id,
        role="user",
        event_type=event.kind.value,
        content=event.text,
        source_event_id=event.event_id,
        created_at=event.created_at.isoformat(),
        metadata={
            "source": event.source.value,
            "attachment_count": len(event.attachments),
        },
    )


def _trace_id(event: CanonicalEvent) -> str:
    return f"trace:{event.event_id}:{uuid4().hex[:12]}"


def _add_trace_event(
    debug_traces,
    *,
    trace_id: str,
    stage: TraceStage,
    level: TraceLevel,
    message: str,
    payload: dict[str, object] | None = None,
    created_at: str,
) -> None:
    debug_traces.add_event(
        DebugTraceEventRecord(
            trace_event_id=f"{trace_id}:{stage.value}:{uuid4().hex[:12]}",
            trace_id=trace_id,
            stage=stage.value,
            level=level.value,
            message=message,
            payload=redact_payload(payload or {}),
            created_at=created_at,
        )
    )


def _add_workflow_trace_events(debug_traces, trace_id: str, result: WorkflowResult) -> None:
    for trace_event in result.trace_events:
        debug_traces.add_event(
            DebugTraceEventRecord(
                trace_event_id=f"{trace_id}:workflow-detail:{uuid4().hex[:12]}",
                trace_id=trace_id,
                stage=str(trace_event.stage),
                level=trace_event.level.value,
                message=trace_event.message,
                payload=redact_payload(trace_event.payload),
                created_at=trace_event.created_at.isoformat(),
            )
        )


def _add_render_trace_event(debug_traces, trace_id: str, result: WorkflowResult, event: CanonicalEvent) -> None:
    file_messages = tuple(message for message in result.messages if message.content_type == "image/png")
    _add_trace_event(
        debug_traces,
        trace_id=trace_id,
        stage=TraceStage.RENDER,
        level=TraceLevel.INFO if result.error is None else TraceLevel.WARNING,
        message="Visualization render completed." if result.error is None else "Visualization render did not produce an image.",
        payload={
            "image_count": len(file_messages),
            "image_bytes": sum(len(message.content or b"") for message in file_messages),
            "filenames": tuple(message.filename for message in file_messages),
            "error_category": result.error.category.value if result.error is not None else None,
        },
        created_at=event.created_at.isoformat(),
    )


def _outbound_payload(result: WorkflowResult) -> dict[str, object]:
    return {
        "message_count": len(result.messages),
        "message_kinds": tuple(message.kind.value for message in result.messages),
        "file_count": sum(1 for message in result.messages if message.content is not None),
        "file_bytes": sum(len(message.content or b"") for message in result.messages),
        "localized_keys": tuple(
            message.localized_text.key.value
            for message in result.messages
            if message.localized_text is not None
        ),
    }


def _trace_llm_gateway(
    gateway: LLMGateway | None,
    debug_traces,
    trace_id: str,
    event: CanonicalEvent,
) -> LLMGateway | None:
    if gateway is None:
        return None

    def observe(call: LLMCallTrace) -> None:
        _add_trace_event(
            debug_traces,
            trace_id=trace_id,
            stage=TraceStage.LLM,
            level=TraceLevel.INFO if call.status == "success" else TraceLevel.ERROR,
            message=call.operation.value,
            payload={
                "operation": call.operation.value,
                "status": call.status,
                "duration_ms": round(call.duration_ms, 3),
                "max_tokens": call.max_tokens,
                "response_keys": list(call.response_keys),
                "error_type": call.error_type,
                "error_message": call.error_message,
            },
            created_at=event.created_at.isoformat(),
        )

    return LLMGateway(gateway.client, observer=observe)


def _trace_repository_bundle(
    repositories: RepositoryBundle,
    *,
    debug_traces,
    trace_id: str,
    created_at: str,
) -> RepositoryBundle:
    return RepositoryBundle(
        users=_RepositoryTraceProxy("users", repositories.users, debug_traces, trace_id, created_at),
        channels=_RepositoryTraceProxy("channels", repositories.channels, debug_traces, trace_id, created_at),
        history=_RepositoryTraceProxy("history", repositories.history, debug_traces, trace_id, created_at),
        pending_workout_deletes=_RepositoryTraceProxy(
            "pending_workout_deletes",
            repositories.pending_workout_deletes,
            debug_traces,
            trace_id,
            created_at,
        ),
        heart_rate_zones=_RepositoryTraceProxy(
            "heart_rate_zones",
            repositories.heart_rate_zones,
            debug_traces,
            trace_id,
            created_at,
        ),
        attachments=_RepositoryTraceProxy("attachments", repositories.attachments, debug_traces, trace_id, created_at),
        workouts=_RepositoryTraceProxy("workouts", repositories.workouts, debug_traces, trace_id, created_at),
        active_workouts=_RepositoryTraceProxy(
            "active_workouts",
            repositories.active_workouts,
            debug_traces,
            trace_id,
            created_at,
        ),
        workout_streams=_RepositoryTraceProxy(
            "workout_streams",
            repositories.workout_streams,
            debug_traces,
            trace_id,
            created_at,
        ),
        rendered_artifacts=_RepositoryTraceProxy(
            "rendered_artifacts",
            repositories.rendered_artifacts,
            debug_traces,
            trace_id,
            created_at,
        ),
        debug_traces=repositories.debug_traces,
    )


class _RepositoryTraceProxy:
    def __init__(self, repository_name: str, repository: Any, debug_traces: Any, trace_id: str, created_at: str) -> None:
        self._repository_name = repository_name
        self._repository = repository
        self._debug_traces = debug_traces
        self._trace_id = trace_id
        self._created_at = created_at

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._repository, name)
        if not callable(attribute):
            return attribute

        def traced_call(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                result = attribute(*args, **kwargs)
            except Exception as exc:
                _add_trace_event(
                    self._debug_traces,
                    trace_id=self._trace_id,
                    stage=TraceStage.REPOSITORY,
                    level=TraceLevel.ERROR,
                    message=f"{self._repository_name}.{name}",
                    payload={
                        "repository": self._repository_name,
                        "method": name,
                        "status": "error",
                        "duration_ms": round((perf_counter() - started) * 1000, 3),
                        "args": _call_shape(args, kwargs),
                        "error_type": type(exc).__name__,
                    },
                    created_at=self._created_at,
                )
                raise
            _add_trace_event(
                self._debug_traces,
                trace_id=self._trace_id,
                stage=TraceStage.REPOSITORY,
                level=TraceLevel.DEBUG,
                message=f"{self._repository_name}.{name}",
                payload={
                    "repository": self._repository_name,
                    "method": name,
                    "status": "success",
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "args": _call_shape(args, kwargs),
                    "result": _value_shape(result),
                },
                created_at=self._created_at,
            )
            return result

        return traced_call


def _call_shape(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, object]:
    return {
        "positional_types": tuple(type(arg).__name__ for arg in args),
        "keyword_keys": tuple(sorted(kwargs.keys())),
    }


def _value_shape(value: Any) -> dict[str, object]:
    if isinstance(value, tuple):
        return {"type": "tuple", "count": len(value)}
    if isinstance(value, list):
        return {"type": "list", "count": len(value)}
    if isinstance(value, dict):
        return {"type": "dict", "keys": tuple(sorted(str(key) for key in value.keys()))}
    if value is None:
        return {"type": "none"}
    if isinstance(value, (str, int, float, bool)):
        return {"type": type(value).__name__}
    return {"type": type(value).__name__}
