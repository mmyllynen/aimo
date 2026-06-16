from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.events import CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import (
    VisualizationIntent,
    VisualizationIntentInput,
    VisualizationIntentRevisionInput,
    extract_visualization_intent,
    revise_visualization_intent,
)
from storage.repositories import HeartRateZoneRecord, RenderedArtifactRecord, WorkoutPointRecord, WorkoutRecord
from storage.files import write_bytes_under
from storage.unit_of_work import RepositoryBundle
from visualization.service import (
    MissingPrimaryMetricError,
    VisualizationArtifact,
    VisualizationSpecInvalidError,
    render_workout_visualization,
    visualization_validation_context,
)
from workout.references import (
    WorkoutReferenceResolution,
    WorkoutReferenceStatus,
    resolve_workout_selector,
)


@dataclass(frozen=True)
class ResolvedVisualizationRequest:
    workout: WorkoutRecord
    intent: VisualizationIntent
    comparison_workouts: tuple[WorkoutRecord, ...] = ()
    previous_visualization: dict[str, object] | None = None


class MissingHeartRateZonesError(ValueError):
    pass


class VisualizationWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        gateway: LLMGateway | None,
        language: SupportedLanguage,
        artifact_root: Path | None = None,
    ) -> WorkflowResult:
        del language
        try:
            resolved = _resolve_request(event, route, repositories, gateway=gateway)
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Visualization intent extraction failed",
            )
        if resolved is None:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.NO_MATCHING_WORKOUT,
                TranslationKey.ERROR_NO_MATCHING_WORKOUT,
                "No matching workout for visualization",
            )
        if resolved == "ambiguous":
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.AMBIGUOUS_WORKOUT,
                TranslationKey.ERROR_AMBIGUOUS_WORKOUT,
                "Ambiguous workout for visualization",
            )

        points = repositories.workout_streams.list_points(resolved.workout.workout_id)
        heart_rate_zones = repositories.heart_rate_zones.list_for_user(event.user_id)
        try:
            artifact, rendered_intent = _render_with_optional_revision(
                event,
                resolved,
                points,
                heart_rate_zones=heart_rate_zones,
                gateway=gateway,
            )
        except MissingHeartRateZonesError:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.MISSING_METRIC,
                TranslationKey.HR_ZONES_EMPTY,
                "Heart-rate zone visualization requested without configured zones",
            )
        except MissingPrimaryMetricError as exc:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.MISSING_METRIC,
                TranslationKey.ERROR_MISSING_METRIC,
                f"Workout is missing primary metric {exc.metric}",
                params={"metric": exc.metric},
            )
        except VisualizationSpecInvalidError as exc:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.VISUALIZATION_PLAN_INVALID,
                TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID,
                f"Invalid visualization spec: {exc.reason}",
            )
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Visualization intent revision failed",
            )
        if _should_set_current_workout(rendered_intent) and not _is_comparison_intent(rendered_intent):
            repositories.active_workouts.set(
                user_id=event.user_id,
                workout_id=resolved.workout.workout_id,
                updated_at=event.created_at,
            )

        storage_path = f"artifacts/{artifact.filename}"
        storage_status = "not_written_in_skeleton"
        if artifact_root is not None:
            stored_path = write_bytes_under(artifact_root, artifact.filename, artifact.content)
            storage_path = str(stored_path)
            storage_status = "written"
        repositories.rendered_artifacts.add(
            RenderedArtifactRecord(
                artifact_id=f"{event.event_id}:visualization",
                owner_user_id=event.user_id,
                workflow_trace_id=None,
                artifact_type="visualization",
                filename=artifact.filename,
                content_type=artifact.content_type,
                storage_path=storage_path,
                created_at=event.created_at.isoformat(),
                metadata={
                    "workout_id": resolved.workout.workout_id,
                    "channel_id": event.channel_id,
                    "source_event_id": event.event_id,
                    "intent": _intent_payload(rendered_intent),
                    "comparison_workout_ids": [workout.workout_id for workout in resolved.comparison_workouts],
                    "rendered_metrics": list(artifact.rendered_metrics),
                    "missing_metrics": list(artifact.missing_metrics),
                    "scaled_metrics": list(artifact.scaled_metrics),
                    "storage_status": storage_status,
                },
            )
        )
        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.FILE,
                    localized_text=LocalizedText(
                        key=TranslationKey.VISUALIZATION_CREATED,
                        params={"title": resolved.workout.title},
                    ),
                    filename=artifact.filename,
                    content_type=artifact.content_type,
                    content=artifact.content,
                    metadata={
                        "workout_id": resolved.workout.workout_id,
                        "rendered_metrics": artifact.rendered_metrics,
                        "missing_metrics": artifact.missing_metrics,
                        "scaled_metrics": artifact.scaled_metrics,
                    },
                ),
            ),
        )


def _resolve_request(
    event: CanonicalEvent,
    route: RouteDecision,
    repositories: RepositoryBundle,
    *,
    gateway: LLMGateway | None,
) -> ResolvedVisualizationRequest | str | None:
    previous_visualization = _previous_visualization_context(event, repositories)
    intent = _intent(event, route, gateway, previous_visualization=previous_visualization)
    resolved = _resolve_workout(event, intent, repositories)
    if resolved.status == WorkoutReferenceStatus.AMBIGUOUS:
        return "ambiguous"
    if resolved.workout is None:
        return None
    comparison_workouts = _comparison_workouts(event, intent, repositories)
    if _is_comparison_intent(intent) and len(comparison_workouts) < 2:
        return None
    return ResolvedVisualizationRequest(
        workout=resolved.workout,
        intent=intent,
        comparison_workouts=comparison_workouts,
        previous_visualization=previous_visualization,
    )


def _render_with_optional_revision(
    event: CanonicalEvent,
    resolved: ResolvedVisualizationRequest,
    points: tuple[WorkoutPointRecord, ...],
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...],
    gateway: LLMGateway | None,
) -> tuple[VisualizationArtifact, VisualizationIntent]:
    _validate_zone_prerequisite(resolved.intent, heart_rate_zones)
    try:
        return (
            render_workout_visualization(
                resolved.workout,
                points,
                resolved.intent,
                heart_rate_zones=heart_rate_zones,
                comparison_workouts=resolved.comparison_workouts,
            ),
            resolved.intent,
        )
    except VisualizationSpecInvalidError as exc:
        if gateway is None:
            raise
        revision_context = visualization_validation_context(
            resolved.workout,
            points,
            resolved.intent,
            heart_rate_zones=heart_rate_zones,
            comparison_workouts=resolved.comparison_workouts,
        )
        validation_errors = revision_context.validation_errors or exc.validation_errors
        revised_intent = revise_visualization_intent(
            gateway,
            VisualizationIntentRevisionInput(
                user_text=event.text,
                failed_intent=_intent_payload(resolved.intent),
                validation_errors=validation_errors,
                dataset_manifest=revision_context.dataset_manifest,
                allowed_primitives=revision_context.allowed_primitives,
                previous_visualization=resolved.previous_visualization,
            ),
        )
        _validate_zone_prerequisite(revised_intent, heart_rate_zones)
        return (
            render_workout_visualization(
                resolved.workout,
                points,
                revised_intent,
                heart_rate_zones=heart_rate_zones,
                comparison_workouts=resolved.comparison_workouts,
            ),
            revised_intent,
        )


def _validate_zone_prerequisite(intent: VisualizationIntent, heart_rate_zones: tuple[HeartRateZoneRecord, ...]) -> None:
    if "heart_rate_zone_seconds" in intent.y_metrics and not heart_rate_zones:
        raise MissingHeartRateZonesError


def _intent(
    event: CanonicalEvent,
    route: RouteDecision,
    gateway: LLMGateway | None,
    *,
    previous_visualization: dict[str, object] | None = None,
) -> VisualizationIntent:
    structured_intent = _structured_intent(event)
    if structured_intent is not None:
        return structured_intent
    if gateway is not None:
        return extract_visualization_intent(
            gateway,
            VisualizationIntentInput(
                user_text=event.text,
                compact_routing_context={
                    "route_confidence": route.confidence.value,
                    "route_reason": route.reason,
                    "has_previous_visualization": previous_visualization is not None,
                },
                previous_visualization=previous_visualization,
            ),
        )
    raise LLMGatewayError("Visualization intent extraction requires an LLM gateway or structured command options")


def _structured_intent(event: CanonicalEvent) -> VisualizationIntent | None:
    command_name = str(event.metadata.get("command_name", "")).strip().lower()
    if command_name not in {"visualisointi", "visualization"}:
        return None
    options = event.metadata.get("options", {})
    if not isinstance(options, dict):
        return None
    y_metrics = _string_tuple(options.get("y_metrics") or options.get("metrics"))
    if not y_metrics:
        return None
    transforms = _string_tuple(options.get("transforms"))
    return VisualizationIntent(
        workout_selector=_structured_selector(options.get("workout_selector") or options.get("selector")),
        x_metric=str(options.get("x_metric") or "elapsed_s"),
        y_metrics=y_metrics,
        transforms=transforms,
        date_range=options.get("date_range") if isinstance(options.get("date_range"), dict) else {},
        comparison_mode=str(options.get("comparison_mode") or ""),
        layout_mode=str(options.get("layout_mode") or "auto"),
        chart_kind=str(options.get("chart_kind") or "auto"),
        context_update={"set_current_workout": bool(options.get("set_current_workout", False))},
    )


def _structured_selector(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        return {"type": "id", "value": value.strip()}
    return {"type": "latest"}


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _previous_visualization_context(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
) -> dict[str, object] | None:
    artifact = repositories.rendered_artifacts.latest_visualization_for_user(
        event.user_id,
        channel_id=event.channel_id,
    )
    if artifact is None:
        return None
    metadata = artifact.metadata
    intent = metadata.get("intent")
    if not isinstance(intent, dict):
        return None
    return {
        "artifact_id": artifact.artifact_id,
        "workout_id": metadata.get("workout_id", ""),
        "channel_id": metadata.get("channel_id", ""),
        "intent": intent,
        "rendered_metrics": metadata.get("rendered_metrics", []),
        "scaled_metrics": metadata.get("scaled_metrics", []),
        "comparison_workout_ids": metadata.get("comparison_workout_ids", []),
    }


def _intent_payload(intent: VisualizationIntent) -> dict[str, object]:
    return {
        "workout_selector": intent.workout_selector,
        "x_metric": intent.x_metric,
        "y_metrics": list(intent.y_metrics),
        "transforms": list(intent.transforms),
        "date_range": intent.date_range,
        "comparison_mode": intent.comparison_mode,
        "layout_mode": intent.layout_mode,
        "chart_kind": intent.chart_kind,
        "context_update": intent.context_update,
    }


def _resolve_workout(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    repositories: RepositoryBundle,
) -> WorkoutReferenceResolution:
    selector = intent.workout_selector
    resolved = resolve_workout_selector(repositories, event.user_id, selector, default="latest")
    return resolved


def _comparison_workouts(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    repositories: RepositoryBundle,
) -> tuple[WorkoutRecord, ...]:
    if not _is_comparison_intent(intent):
        return ()
    count = _comparison_count(intent)
    return repositories.workouts.list_for_user(event.user_id, limit=count)


def _comparison_count(intent: VisualizationIntent) -> int:
    selector = intent.workout_selector
    if isinstance(selector, dict):
        count = selector.get("count") or selector.get("limit")
        if isinstance(count, int) and count > 1:
            return min(count, 10)
        if isinstance(count, str) and count.isdecimal() and int(count) > 1:
            return min(int(count), 10)
    return 2


def _is_comparison_intent(intent: VisualizationIntent) -> bool:
    comparison = intent.comparison_mode.strip().lower()
    return comparison not in {"", "none", "single"}


def _should_set_current_workout(intent: VisualizationIntent) -> bool:
    update = intent.context_update
    return isinstance(update, dict) and update.get("set_current_workout") is True


def _error_result(
    status: WorkflowStatus,
    category: ErrorCategory,
    message_key: TranslationKey,
    message: str,
    *,
    params: dict[str, object] | None = None,
) -> WorkflowResult:
    return WorkflowResult(
        status=status,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=message_key, params=params or {}),
            ),
        ),
        error=AppError(
            category=category,
            message=message,
            user_message_key=message_key.value,
            user_message_params=params or {},
        ),
    )
