from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.policy import AdminPolicy
from app.redaction import redact_payload
from core.events import CanonicalEvent, EventKind
from core.i18n import DEFAULT_LANGUAGE, SupportedLanguage
from core.routing import RouteConfidence, RouteDecision, WorkflowTarget
from core.workflows import WorkflowResult
from llm.gateway import LLMGateway
from storage.repositories import DebugTraceEventRecord, HistoryEventRecord
from storage.unit_of_work import UnitOfWork
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
            repositories.users.touch(
                user_id=event.user_id,
                discord_user_name=event.user_name,
                discord_display_name=str(event.metadata.get("discord_display_name", "")),
                seen_at=event.created_at,
                source=event.source.value,
            )
            repositories.channels.upsert(
                channel_id=event.channel_id,
                guild_id=event.guild_id,
            )
            repositories.history.add(_history_record(event))

            route = route_event(event)
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
            repositories.debug_traces.add_event(
                DebugTraceEventRecord(
                    trace_event_id=f"{trace_id}:route",
                    trace_id=trace_id,
                    stage="route",
                    level="info",
                    message=route.reason,
                    payload=redact_payload({
                        "target": route.target.value,
                        "confidence": route.confidence.value,
                        "slots": route.slots,
                    }),
                    created_at=event.created_at.isoformat(),
                )
            )

            if route.target == WorkflowTarget.HELP:
                result = self.help_workflow.handle(event, route)
            elif route.target == WorkflowTarget.DEBUG:
                result = self.debug_workflow.handle(
                    event,
                    route,
                    repositories,
                    admin_policy=context.admin_policy,
                    current_trace_id=trace_id,
                )
            elif route.target == WorkflowTarget.WORKOUT_MANAGEMENT:
                result = self.workout_management_workflow.handle(event, route, repositories)
            elif route.target == WorkflowTarget.GPX_INGEST:
                result = self.gpx_ingest_workflow.handle(
                    event,
                    route,
                    repositories,
                    max_attachment_size_bytes=context.max_attachment_size_bytes,
                )
            elif route.target == WorkflowTarget.VISUALIZATION:
                result = self.visualization_workflow.handle(
                    event,
                    route,
                    repositories,
                    gateway=context.llm_gateway,
                    language=context.language,
                )
            elif route.target == WorkflowTarget.WORKOUT_CHAT:
                result = self.workout_chat_workflow.handle(
                    event,
                    route,
                    repositories,
                    gateway=context.llm_gateway,
                    language=context.language,
                )
            elif route.target == WorkflowTarget.CHAT:
                result = self.chat_workflow.handle(
                    event,
                    route,
                    repositories,
                    gateway=context.llm_gateway,
                    language=context.language,
                )
            else:
                result = self.noop_workflow.handle(event, route)

            repositories.debug_traces.finish(
                trace_id,
                status=result.status.value,
                finished_at=event.created_at,
            )
            repositories.debug_traces.add_event(
                DebugTraceEventRecord(
                    trace_event_id=f"{trace_id}:result",
                    trace_id=trace_id,
                    stage="result",
                    level="info",
                    message=result.status.value,
                    payload=redact_payload({
                        "message_count": len(result.messages),
                        "state_update_count": len(result.state_updates),
                        "has_error": result.error is not None,
                    }),
                    created_at=event.created_at.isoformat(),
                )
            )
            repositories.debug_traces.prune_to_limit(keep=context.trace_keep_limit)
            return result


def route_event(event: CanonicalEvent) -> RouteDecision:
    if event.kind == EventKind.MESSAGE:
        return RouteDecision(
            target=WorkflowTarget.CHAT,
            confidence=RouteConfidence.LOW,
            reason="Normal non-mention message is stored but not handled.",
        )

    command_name = str(event.metadata.get("command_name", "")).lower()
    text = event.text.strip().lower()
    if event.attachments and _has_gpx_attachment(event):
        return RouteDecision(
            target=WorkflowTarget.GPX_INGEST,
            confidence=RouteConfidence.HIGH,
            slots={
                "attachment_ids": [attachment.attachment_id for attachment in event.attachments],
            },
            reason="Supported GPX attachment present.",
        )
    if _is_visualization_request(event):
        return RouteDecision(
            target=WorkflowTarget.VISUALIZATION,
            confidence=RouteConfidence.MEDIUM,
            reason="Visualization request skeleton matched chart language.",
        )
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
    if _is_workout_chat_request(event):
        return RouteDecision(
            target=WorkflowTarget.WORKOUT_CHAT,
            confidence=RouteConfidence.MEDIUM,
            reason="Workout chat request skeleton matched workout language.",
        )
    return RouteDecision(
        target=WorkflowTarget.CHAT,
        confidence=RouteConfidence.LOW,
        reason="No deterministic skeleton route matched.",
    )


def _is_help_request(event: CanonicalEvent) -> bool:
    command_name = str(event.metadata.get("command_name", "")).lower()
    options = event.metadata.get("options", {})
    if isinstance(options, dict) and options.get("apua") is True:
        return True
    text = event.text.strip().lower()
    return command_name in {"help"} or text in {"apua", "help", "/help", "/aimo"}


def _has_gpx_attachment(event: CanonicalEvent) -> bool:
    return any(
        attachment.filename.lower().endswith(".gpx")
        or attachment.content_type.strip().lower() in {"application/gpx+xml", "application/xml", "text/xml"}
        for attachment in event.attachments
    )


def _is_visualization_request(event: CanonicalEvent) -> bool:
    command_name = str(event.metadata.get("command_name", "")).lower()
    if command_name in {"visualisointi", "visualization"}:
        return True
    text = event.text.strip().lower()
    markers = ("piirrä", "piirra", "kuvaaja", "käyrä", "kayra", "plot", "draw", "chart")
    return any(marker in text for marker in markers)


def _is_workout_chat_request(event: CanonicalEvent) -> bool:
    text = event.text.strip().lower()
    workout_markers = ("treeni", "harjoitus", "lenkki", "workout", "run", "training")
    question_markers = (
        "miten",
        "miltä",
        "milta",
        "kerro",
        "analysoi",
        "arvioi",
        "palaut",
        "onnistu",
        "how",
        "analyze",
        "review",
        "recover",
    )
    return any(marker in text for marker in workout_markers) and any(marker in text for marker in question_markers)


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
