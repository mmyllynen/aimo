from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.events import CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import VisualizationIntent, VisualizationIntentInput, extract_visualization_intent
from storage.repositories import RenderedArtifactRecord, WorkoutRecord
from storage.files import write_bytes_under
from storage.unit_of_work import RepositoryBundle
from visualization.metrics import (
    infer_metrics_from_text,
    infer_transforms_from_text,
    infer_x_metric_from_text,
)
from visualization.service import MissingPrimaryMetricError, VisualizationSpecInvalidError, render_workout_visualization
from workout.references import (
    WorkoutReferenceResolution,
    WorkoutReferenceStatus,
    resolve_workout_reference,
    resolve_workout_selector,
)


@dataclass(frozen=True)
class ResolvedVisualizationRequest:
    workout: WorkoutRecord
    intent: VisualizationIntent


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
            artifact = render_workout_visualization(
                resolved.workout,
                points,
                resolved.intent,
                heart_rate_zones=heart_rate_zones,
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
    intent = _intent(event, route, gateway)
    resolved = _resolve_workout(event, intent, repositories)
    if resolved.status == WorkoutReferenceStatus.AMBIGUOUS:
        return "ambiguous"
    if resolved.workout is None:
        return None
    return ResolvedVisualizationRequest(workout=resolved.workout, intent=intent)


def _intent(event: CanonicalEvent, route: RouteDecision, gateway: LLMGateway | None) -> VisualizationIntent:
    if gateway is not None:
        return extract_visualization_intent(
            gateway,
            VisualizationIntentInput(
                user_text=event.text,
                compact_routing_context={
                    "route_confidence": route.confidence.value,
                    "route_reason": route.reason,
                },
            ),
        )
    selector = "active" if "aktiiv" in event.text.lower() or "active" in event.text.lower() else "latest"
    return VisualizationIntent(
        workout_selector={"type": selector},
        x_metric=infer_x_metric_from_text(event.text),
        y_metrics=infer_metrics_from_text(event.text),
        transforms=infer_transforms_from_text(event.text),
        date_range={},
        comparison_mode="",
    )


def _resolve_workout(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    repositories: RepositoryBundle,
) -> WorkoutReferenceResolution:
    selector = intent.workout_selector
    resolved = resolve_workout_selector(repositories, event.user_id, selector, default="latest")
    if resolved.status == WorkoutReferenceStatus.NOT_FOUND and isinstance(selector, dict) and not selector.get("value"):
        return resolve_workout_reference(repositories, event.user_id, event.text, default="latest")
    return resolved


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
