from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.config import MapsConfig, RenderersConfig
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
    period_visualization_validation_context,
    render_period_visualization,
    render_workout_visualization,
    visualization_validation_context,
)
from visualization.datasets import resolve_datasets, dataset_request_from_metrics
from workout.periods import PeriodBounds, PeriodRequestError, local_now, resolve_period_bounds
from llm.operations import PeriodRequest
from workout.references import (
    WorkoutReferenceResolution,
    WorkoutReferenceStatus,
    resolve_workout_selector,
)


VISUALIZATION_MODIFIER_METRICS = {
    "hr": "heart_rate_bpm",
    "syke": "heart_rate_bpm",
    "heart": "heart_rate_bpm",
    "heartrate": "heart_rate_bpm",
    "heart_rate": "heart_rate_bpm",
    "elevation": "elevation_m",
    "korkeus": "elevation_m",
    "pace": "pace_s_per_km",
    "vauhti": "pace_s_per_km",
    "ascent": "ascent_m",
    "nousu": "ascent_m",
}
ROUTE_COLOR_METRICS = frozenset({"heart_rate_bpm", "elevation_m", "pace_s_per_km"})
VISUALIZATION_ASPECT_SIZES = {
    "portrait": (1080, 1920),
    "square": (1080, 1080),
}


@dataclass(frozen=True)
class ResolvedVisualizationRequest:
    workout: WorkoutRecord
    intent: VisualizationIntent
    comparison_workouts: tuple[WorkoutRecord, ...] = ()
    previous_visualization: dict[str, object] | None = None
    scope_type: str = "single_workout"
    workouts: tuple[WorkoutRecord, ...] = ()
    period_bounds: PeriodBounds | None = None


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
        maps_config: MapsConfig | None = None,
        renderers_config: RenderersConfig | None = None,
    ) -> WorkflowResult:
        try:
            resolved = _resolve_request(event, route, repositories, gateway=gateway, language=language)
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

        points = _points_for_resolved_scope(resolved, repositories)
        heart_rate_zones = repositories.heart_rate_zones.list_for_user(event.user_id)
        try:
            artifact, rendered_intent = _render_with_optional_revision(
                event,
                resolved,
                points,
                heart_rate_zones=heart_rate_zones,
                gateway=gateway,
                tile_cache_root=_tile_cache_root(artifact_root),
                maps_config=maps_config,
                renderers_config=renderers_config,
                language=language,
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
        artifact_metadata = {
            "workout_id": resolved.workout.workout_id,
            "channel_id": event.channel_id,
            "source_event_id": event.event_id,
            "intent": _intent_payload(rendered_intent),
            "comparison_workout_ids": [workout.workout_id for workout in resolved.comparison_workouts],
            "scope_type": resolved.scope_type,
            "workout_ids": [workout.workout_id for workout in resolved.workouts] or [resolved.workout.workout_id],
            "period_start_date": resolved.period_bounds.start_date if resolved.period_bounds else "",
            "period_end_date": resolved.period_bounds.end_date if resolved.period_bounds else "",
            "rendered_metrics": list(artifact.rendered_metrics),
            "missing_metrics": list(artifact.missing_metrics),
            "scaled_metrics": list(artifact.scaled_metrics),
            "storage_status": storage_status,
        }
        if artifact.metadata:
            artifact_metadata.update(artifact.metadata)
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
                metadata=artifact_metadata,
            )
        )
        primary_message = OutgoingMessage(
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
                "scope_type": resolved.scope_type,
                "workout_ids": tuple(workout.workout_id for workout in resolved.workouts)
                or (resolved.workout.workout_id,),
                "rendered_metrics": artifact.rendered_metrics,
                "missing_metrics": artifact.missing_metrics,
                "scaled_metrics": artifact.scaled_metrics,
                **(artifact.metadata or {}),
            },
        )
        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(primary_message, *_route_color_notice_messages(rendered_intent, language=language)),
        )


def _resolve_request(
    event: CanonicalEvent,
    route: RouteDecision,
    repositories: RepositoryBundle,
    *,
    gateway: LLMGateway | None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> ResolvedVisualizationRequest | str | None:
    previous_visualization = _previous_visualization_context(event, repositories)
    intent = _intent(event, route, gateway, previous_visualization=previous_visualization)
    period = _resolve_period_scope(event, intent, repositories, previous_visualization=previous_visualization, language=language)
    if period == "no_match":
        return None
    if period is not None:
        return period
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
        workouts=(resolved.workout,),
    )


def _render_with_optional_revision(
    event: CanonicalEvent,
    resolved: ResolvedVisualizationRequest,
    points: tuple[WorkoutPointRecord, ...],
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...],
    gateway: LLMGateway | None,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    renderers_config: RenderersConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> tuple[VisualizationArtifact, VisualizationIntent]:
    _validate_zone_prerequisite(resolved.intent, heart_rate_zones)
    if resolved.scope_type == "workout_set":
        manifest = _period_manifest(resolved, points, heart_rate_zones)
        try:
            return (
                render_period_visualization(
                    resolved.workout,
                    resolved.intent,
                    manifest=manifest,
                    tile_cache_root=tile_cache_root,
                    maps_config=maps_config,
                    renderers_config=renderers_config,
                    language=language,
                ),
                resolved.intent,
            )
        except VisualizationSpecInvalidError as exc:
            if gateway is None:
                raise
            revision_context = period_visualization_validation_context(
                resolved.workout,
                resolved.intent,
                manifest=manifest,
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
            revised_intent = _apply_visualization_modifiers(revised_intent, event.text)
            _validate_zone_prerequisite(revised_intent, heart_rate_zones)
            revised_manifest = _period_manifest(
                ResolvedVisualizationRequest(
                    workout=resolved.workout,
                    intent=revised_intent,
                    comparison_workouts=resolved.comparison_workouts,
                    previous_visualization=resolved.previous_visualization,
                    scope_type=resolved.scope_type,
                    workouts=resolved.workouts,
                    period_bounds=resolved.period_bounds,
                ),
                points,
                heart_rate_zones,
            )
            return (
                render_period_visualization(
                    resolved.workout,
                    revised_intent,
                    manifest=revised_manifest,
                    tile_cache_root=tile_cache_root,
                    maps_config=maps_config,
                    renderers_config=renderers_config,
                    language=language,
                ),
                revised_intent,
            )
    try:
        return (
            render_workout_visualization(
                resolved.workout,
                points,
                resolved.intent,
                heart_rate_zones=heart_rate_zones,
                comparison_workouts=resolved.comparison_workouts,
                tile_cache_root=tile_cache_root,
                maps_config=maps_config,
                renderers_config=renderers_config,
                language=language,
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
        revised_intent = _apply_visualization_modifiers(revised_intent, event.text)
        _validate_zone_prerequisite(revised_intent, heart_rate_zones)
        return (
            render_workout_visualization(
                resolved.workout,
                points,
                revised_intent,
                heart_rate_zones=heart_rate_zones,
                comparison_workouts=resolved.comparison_workouts,
                tile_cache_root=tile_cache_root,
                maps_config=maps_config,
                renderers_config=renderers_config,
                language=language,
            ),
            revised_intent,
        )


def _tile_cache_root(artifact_root: Path | None) -> Path | None:
    if artifact_root is None:
        return None
    return artifact_root.parent / "data" / "cache" / "osm_tiles"


def _validate_zone_prerequisite(intent: VisualizationIntent, heart_rate_zones: tuple[HeartRateZoneRecord, ...]) -> None:
    if "heart_rate_zone_seconds" in intent.y_metrics and not heart_rate_zones:
        raise MissingHeartRateZonesError


def _resolve_period_scope(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    repositories: RepositoryBundle,
    *,
    previous_visualization: dict[str, object] | None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> ResolvedVisualizationRequest | str | None:
    selector = intent.workout_selector if isinstance(intent.workout_selector, dict) else {}
    selector_type = _period_selector_type(intent)
    if selector_type not in {
        "all_workouts",
        "current_week",
        "last_week",
        "current_month",
        "last_month",
        "rolling_days",
        "date_range",
        "calendar_year_to_date",
    }:
        return None
    try:
        bounds = resolve_period_bounds(_period_request_from_intent(intent), local_now(event.created_at))
    except PeriodRequestError:
        return "no_match"
    workouts = repositories.workouts.list_for_user_in_period(
        event.user_id,
        start_date=bounds.start_date,
        end_date=bounds.end_date,
    )
    if not workouts:
        return "no_match"
    return ResolvedVisualizationRequest(
        workout=_period_title_workout(event, intent, bounds, workouts, language=language),
        intent=intent,
        comparison_workouts=(),
        previous_visualization=previous_visualization,
        scope_type="workout_set",
        workouts=workouts,
        period_bounds=bounds,
    )


def _period_request_from_intent(intent: VisualizationIntent) -> PeriodRequest:
    selector = intent.workout_selector if isinstance(intent.workout_selector, dict) else {}
    selector_type = _period_selector_type(intent)
    date_range = intent.date_range if isinstance(intent.date_range, dict) else {}
    rolling_days = selector.get("count") or selector.get("limit")
    if isinstance(rolling_days, str) and rolling_days.isdecimal():
        rolling_days = int(rolling_days)
    if not isinstance(rolling_days, int):
        rolling_days = None
    return PeriodRequest(
        scope_type=selector_type,
        scope_value=str(selector.get("value", "") or ""),
        start_date=str(date_range.get("start", "") or ""),
        end_date=str(date_range.get("end", "") or ""),
        rolling_days=rolling_days,
        filters={},
        metrics=tuple(intent.y_metrics),
        grouping="none",
        output_mode="visualization",
        comparison_mode="none",
    )


def _period_selector_type(intent: VisualizationIntent) -> str:
    selector = intent.workout_selector if isinstance(intent.workout_selector, dict) else {}
    selector_type = str(selector.get("type", "")).strip()
    date_range = intent.date_range if isinstance(intent.date_range, dict) else {}
    if selector_type == "date" and date_range.get("start") and date_range.get("end"):
        return "date_range"
    return selector_type


def _period_title_workout(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    bounds: PeriodBounds,
    workouts: tuple[WorkoutRecord, ...],
    *,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> WorkoutRecord:
    title = _period_title(intent, bounds, language=language)
    distance = sum(workout.distance_km or 0.0 for workout in workouts)
    duration = sum(workout.duration_s or 0.0 for workout in workouts)
    ascent = sum(workout.ascent_m or 0.0 for workout in workouts)
    avg_hr_values = tuple(workout.avg_hr_bpm for workout in workouts if workout.avg_hr_bpm is not None)
    max_hr_values = tuple(workout.max_hr_bpm for workout in workouts if workout.max_hr_bpm is not None)
    now = event.created_at.isoformat()
    return WorkoutRecord(
        workout_id=f"period-{event.event_id}",
        owner_user_id=event.user_id,
        source_attachment_id=None,
        guild_id=event.guild_id,
        channel_id=event.channel_id,
        title=title,
        kind="period",
        primary_kind="period",
        start_time_utc=None,
        start_time_local=None,
        local_date=_period_date_label(bounds),
        distance_km=distance if workouts else None,
        duration_s=duration if workouts else None,
        pace_s_per_km=None,
        ascent_m=ascent if workouts else None,
        avg_hr_bpm=(sum(avg_hr_values) / len(avg_hr_values)) if avg_hr_values else None,
        max_hr_bpm=max(max_hr_values) if max_hr_values else None,
        point_count=sum(workout.point_count for workout in workouts),
        created_at=now,
    )


def _period_title(intent: VisualizationIntent, bounds: PeriodBounds, *, language: SupportedLanguage = SupportedLanguage.FI) -> str:
    selector = intent.workout_selector if isinstance(intent.workout_selector, dict) else {}
    selector_type = str(selector.get("type", "")).strip()
    labels = _period_title_labels(language)
    return labels.get(selector_type, bounds.label.replace("_", " ").title())


def _period_title_labels(language: SupportedLanguage) -> dict[str, str]:
    if language == SupportedLanguage.FI:
        return {
            "all_workouts": "Kaikki treenit",
            "current_week": "Tämä viikko",
            "last_week": "Viime viikko",
            "current_month": "Tämä kuukausi",
            "last_month": "Viime kuukausi",
            "rolling_days": "Liukuva jakso",
            "date_range": "Valittu jakso",
            "calendar_year_to_date": "Kuluva vuosi",
        }
    return {
        "all_workouts": "All workouts",
        "current_week": "Current week",
        "last_week": "Last week",
        "current_month": "Current month",
        "last_month": "Last month",
        "rolling_days": "Rolling period",
        "date_range": "Selected period",
        "calendar_year_to_date": "Year to date",
    }


def _period_date_label(bounds: PeriodBounds) -> str:
    if bounds.start_date and bounds.end_date:
        return f"{bounds.start_date}..{bounds.end_date}"
    return ""


def _points_for_resolved_scope(
    resolved: ResolvedVisualizationRequest,
    repositories: RepositoryBundle,
) -> tuple[WorkoutPointRecord, ...]:
    if resolved.scope_type != "workout_set":
        return repositories.workout_streams.list_points(resolved.workout.workout_id)
    points: list[WorkoutPointRecord] = []
    for workout in resolved.workouts:
        points.extend(repositories.workout_streams.list_points(workout.workout_id))
    return tuple(points)


def _period_manifest(
    resolved: ResolvedVisualizationRequest,
    points: tuple[WorkoutPointRecord, ...],
    heart_rate_zones: tuple[HeartRateZoneRecord, ...],
):
    request = dataset_request_from_metrics(
        x_metric=resolved.intent.x_metric,
        y_metrics=resolved.intent.y_metrics,
        transforms=resolved.intent.transforms,
        comparison=False,
        chart_kind=resolved.intent.chart_kind,
    )
    return resolve_datasets(
        request,
        points=points,
        heart_rate_zones=heart_rate_zones,
        workout=resolved.workout,
        period_workouts=resolved.workouts,
    )


def _intent(
    event: CanonicalEvent,
    route: RouteDecision,
    gateway: LLMGateway | None,
    *,
    previous_visualization: dict[str, object] | None = None,
) -> VisualizationIntent:
    structured_intent = _structured_intent(event)
    if structured_intent is not None:
        return _apply_visualization_modifiers(structured_intent, event.text)
    if gateway is not None:
        intent = extract_visualization_intent(
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
        return _apply_visualization_modifiers(intent, event.text)
    raise LLMGatewayError("Visualization intent extraction requires an LLM gateway or structured command options")


def _apply_visualization_modifiers(intent: VisualizationIntent, text: str) -> VisualizationIntent:
    modifiers = _visualization_modifiers(text)
    if not modifiers:
        return intent
    extra_metrics = tuple(VISUALIZATION_MODIFIER_METRICS[modifier] for modifier in modifiers if modifier in VISUALIZATION_MODIFIER_METRICS)
    render_size = next((VISUALIZATION_ASPECT_SIZES[modifier] for modifier in modifiers if modifier in VISUALIZATION_ASPECT_SIZES), None)
    if not extra_metrics and render_size is None:
        return intent
    route_color_metric = intent.route_color_metric
    ignored_route_metrics: tuple[str, ...] = ()
    if intent.chart_kind == "map" and "route" in intent.y_metrics:
        route_metrics = tuple(metric for metric in extra_metrics if metric in ROUTE_COLOR_METRICS)
        if route_metrics:
            route_color_metric = route_metrics[0]
            ignored_route_metrics = route_metrics[1:]
            extra_metrics = (route_color_metric,)
    y_metrics = tuple(dict.fromkeys((*intent.y_metrics, *extra_metrics)))
    return VisualizationIntent(
        workout_selector=intent.workout_selector,
        x_metric=intent.x_metric,
        y_metrics=y_metrics,
        transforms=intent.transforms,
        date_range=intent.date_range,
        comparison_mode=intent.comparison_mode,
        layout_mode=intent.layout_mode,
        chart_kind=intent.chart_kind,
        context_update=intent.context_update,
        route_color_metric=route_color_metric,
        route_color_ignored_metrics=ignored_route_metrics,
        render_width=render_size[0] if render_size is not None else intent.render_width,
        render_height=render_size[1] if render_size is not None else intent.render_height,
    )


def _visualization_modifiers(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(1).lower().replace("-", "_") for match in re.finditer(r"(?<!\w)\+([\w-]+)", text)))


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
        "route_color_metric": intent.route_color_metric,
        "route_color_ignored_metrics": list(intent.route_color_ignored_metrics),
        "render_width": intent.render_width,
        "render_height": intent.render_height,
    }


def _route_color_notice_messages(intent: VisualizationIntent, *, language: SupportedLanguage) -> tuple[OutgoingMessage, ...]:
    if not intent.route_color_metric or not intent.route_color_ignored_metrics:
        return ()
    return (
        OutgoingMessage(
            kind=OutgoingKind.TEXT,
            localized_text=LocalizedText(
                key=TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED,
                params={"metric": _route_color_metric_label(intent.route_color_metric, language=language)},
            ),
            metadata={
                "route_color_metric": intent.route_color_metric,
                "route_color_ignored_metrics": intent.route_color_ignored_metrics,
            },
        ),
    )


def _route_color_metric_label(metric: str, *, language: SupportedLanguage) -> str:
    if language == SupportedLanguage.FI:
        labels = {
            "heart_rate_bpm": "syke",
            "elevation_m": "korkeus",
            "pace_s_per_km": "vauhti",
        }
        return labels.get(metric, metric)
    labels = {
        "heart_rate_bpm": "heart rate",
        "elevation_m": "elevation",
        "pace_s_per_km": "pace",
    }
    return labels.get(metric, metric)


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
