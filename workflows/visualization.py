from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from core.config import MapsConfig, PublicArtifactsConfig
from core.events import CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import (
    RouteTimeEstimateIntentInput,
    VisualizationIntent,
    VisualizationIntentInput,
    VisualizationIntentRevisionInput,
    extract_visualization_intent,
    interpret_route_time_estimate_intent,
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
from visualization.animation import (
    OverlayAnimationEncodingError,
    OverlayAnimationEncoderUnavailableError,
    OverlayAnimationRequest,
    render_workout_overlay_bundle,
)
from visualization.datasets import resolve_datasets, dataset_request_from_metrics
from workout.gpx import GpxParseError, parse_gpx
from workout.periods import DEFAULT_PERIOD_TIMEZONE, PeriodBounds, PeriodRequestError, local_now, resolve_period_bounds
from llm.operations import PeriodRequest
from workout.references import (
    WorkoutReferenceResolution,
    WorkoutReferenceStatus,
    resolve_workout_selector,
)
from workout.route_estimate import estimate_route_time_from_features
from workout.route_time_summary import build_route_time_weather_payload, format_route_time_title_summary
from weather.service import WeatherProvider


VISUALIZATION_MODIFIER_METRICS = {
    "hr": "heart_rate_bpm",
    "syke": "heart_rate_bpm",
    "heart": "heart_rate_bpm",
    "heartrate": "heart_rate_bpm",
    "heart_rate": "heart_rate_bpm",
    "elevation": "elevation_m",
    "korkeus": "elevation_m",
    "grade": "grade",
    "jyrkkyys": "grade",
    "kaltevuus": "grade",
    "pace": "pace_s_per_km",
    "vauhti": "pace_s_per_km",
    "ascent": "ascent_m",
    "nousu": "ascent_m",
    "nousumetrit": "ascent_m",
    "pace": "pace_s_per_km",
    "vauhti": "pace_s_per_km",
    "distance": "distance_km",
    "matka": "distance_km",
    "duration": "duration_s",
    "kesto": "duration_s",
    "date": "local_date",
    "paiva": "local_date",
    "päivä": "local_date",
    "maxhr": "max_hr_bpm",
    "maksimisyke": "max_hr_bpm",
}
ROUTE_COLOR_METRICS = frozenset({"heart_rate_bpm", "elevation_m", "grade", "pace_s_per_km"})
SOCIAL_ROUTE_COLOR_MODIFIER_METRICS = {
    modifier: metric
    for modifier, metric in VISUALIZATION_MODIFIER_METRICS.items()
    if metric in ROUTE_COLOR_METRICS
}
SOCIAL_STAT_MODIFIER_METRICS = {
    **VISUALIZATION_MODIFIER_METRICS,
    "hr": "avg_hr_bpm",
    "syke": "avg_hr_bpm",
    "heart": "avg_hr_bpm",
    "heartrate": "avg_hr_bpm",
    "heart_rate": "avg_hr_bpm",
}
VISUALIZATION_ASPECT_SIZES = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "square": (1080, 1080),
}
SOCIAL_OUTPUT_MODIFIERS = frozenset({"social", "somekuva"})
SOCIAL_STYLE_PRESETS = frozenset({"classic", "minimal", "poster", "routeonly", "data", "photo"})
WAYPOINT_HIDE_MODIFIERS = frozenset({"waypoints", "reittimerkit"})
ROUTE_DIRECTION_MODIFIERS = frozenset({"direction", "suunta"})
ELEVATION_OVERLAY_SHOW_MODIFIERS = frozenset({"overlay:elevation", "overlay:korkeus"})
ELEVATION_OVERLAY_HIDE_MODIFIERS = frozenset({"overlay:elevation", "overlay:korkeus"})
SOCIAL_STYLE_ENUMS = {
    "crop": frozenset({"center", "top", "bottom", "left", "right"}),
    "filter": frozenset({"none", "warm", "cool", "bw", "vivid", "matte"}),
    "route_size": frozenset({"small", "normal", "large", "huge"}),
    "title": frozenset({"top", "bottom", "hide"}),
    "title_align": frozenset({"left", "center"}),
    "stats": frozenset({"left", "right", "bottom", "hide"}),
    "panel": frozenset({"dark", "light", "none"}),
    "font": frozenset({"clean", "bold", "mono", "serif"}),
    "route_pos": frozenset({"center", "top", "bottom", "left", "right"}),
    "stats_style": frozenset({"compact", "large", "stacked"}),
}
SOCIAL_STYLE_BOOLEAN_KEYS = frozenset({"route_shadow", "markers"})
SOCIAL_STYLE_INTEGER_RANGES = {
    "dim": (0, 70),
    "blur": (0, 20),
}
SOCIAL_STYLE_COLOR_KEYS = frozenset({"route", "text", "accent"})
SOCIAL_STYLE_COLOR_NAMES = frozenset({"default", "auto", "blue", "white", "black", "red", "green", "yellow"})
SOCIAL_STYLE_ALIASES = {
    "background_crop": "crop",
    "background_dim": "dim",
    "darken": "dim",
    "tummennus": "dim",
    "filtteri": "filter",
    "suodatin": "filter",
    "reitti": "route",
    "route_color": "route",
    "reitin_vari": "route",
    "reitin_väri": "route",
    "route_width": "route_size",
    "reitin_koko": "route_size",
    "shadow": "route_shadow",
    "varjo": "route_shadow",
    "markerit": "markers",
    "otsikko": "title",
    "title_position": "title",
    "stats_position": "stats",
    "data": "stats",
    "paneeli": "panel",
    "teksti": "text",
    "koroste": "accent",
    "sumennus": "blur",
    "route_position": "route_pos",
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
        public_artifacts: PublicArtifactsConfig | None = None,
        maps_config: MapsConfig | None = None,
        weather_provider: WeatherProvider | None = None,
    ) -> WorkflowResult:
        if _is_animation_overlay_request(event, route):
            return _handle_animation_overlay(
                event,
                repositories,
                language=language,
                artifact_root=artifact_root,
                public_artifacts=public_artifacts,
                maps_config=maps_config,
            )
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

        resolved = _backfill_waypoints_from_raw_gpx(resolved, repositories)
        points = _points_for_resolved_scope(resolved, repositories)
        heart_rate_zones = repositories.heart_rate_zones.list_for_user(event.user_id)
        try:
            artifact, rendered_intent = _render_with_optional_revision(
                event,
                resolved,
                points,
                repositories,
                heart_rate_zones=heart_rate_zones,
                gateway=gateway,
                tile_cache_root=_tile_cache_root(artifact_root),
                maps_config=maps_config,
                weather_provider=weather_provider,
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
            if rendered_intent_if_available := _social_route_error_key(resolved.intent, exc):
                return _error_result(
                    WorkflowStatus.USER_ERROR,
                    ErrorCategory.MISSING_METRIC,
                    rendered_intent_if_available,
                    "Social image requested for workout without route points",
                )
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
    intent = _intent(event, route, repositories, gateway, previous_visualization=previous_visualization)
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
    repositories: RepositoryBundle,
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...],
    gateway: LLMGateway | None,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    weather_provider: WeatherProvider | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> tuple[VisualizationArtifact, VisualizationIntent]:
    _validate_zone_prerequisite(resolved.intent, heart_rate_zones)
    if resolved.scope_type == "workout_set":
        if resolved.intent.output_mode == "social_image":
            raise VisualizationSpecInvalidError("SocialImageRequiresSingleWorkout")
        manifest = _period_manifest(resolved, points, heart_rate_zones)
        try:
            return (
                render_period_visualization(
                    resolved.workout,
                    resolved.intent,
                    manifest=manifest,
                    tile_cache_root=tile_cache_root,
                    maps_config=maps_config,
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
                    language=language,
                ),
                revised_intent,
            )
    try:
        route_time = _route_time_title_context(
            event,
            resolved,
            points,
            repositories=repositories,
            gateway=gateway,
            weather_provider=weather_provider,
            language=language,
        )
        return (
                render_workout_visualization(
                resolved.workout,
                points,
                resolved.intent,
                heart_rate_zones=heart_rate_zones,
                comparison_workouts=resolved.comparison_workouts,
                tile_cache_root=tile_cache_root,
                maps_config=maps_config,
                language=language,
                social_background_image=_social_background_image(event),
                route_time_title_summary=route_time["title_summary"],
                route_time_metadata=route_time["metadata"],
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
                language=language,
                social_background_image=_social_background_image(event),
                route_time_title_summary=route_time["title_summary"],
                route_time_metadata=route_time["metadata"],
            ),
            revised_intent,
        )


def _tile_cache_root(artifact_root: Path | None) -> Path | None:
    if artifact_root is None:
        return None
    return artifact_root.parent / "data" / "cache" / "osm_tiles"


def _is_animation_overlay_request(event: CanonicalEvent, route: RouteDecision) -> bool:
    return route.slots.get("animation_overlay") is True or bool(_overlay_tarkenne_values(event.text))


def _handle_animation_overlay(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    *,
    language: SupportedLanguage,
    artifact_root: Path | None,
    public_artifacts: PublicArtifactsConfig | None,
    maps_config: MapsConfig | None,
) -> WorkflowResult:
    del language
    workout = _resolve_animation_workout(event, repositories)
    if workout is None:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.NO_MATCHING_WORKOUT,
            TranslationKey.ERROR_NO_MATCHING_WORKOUT,
            "No matching workout for animation overlay",
        )
    points = repositories.workout_streams.list_points(workout.workout_id)
    request = _animation_request(event.text)
    try:
        artifacts = render_workout_overlay_bundle(
            workout,
            points,
            request,
            tile_cache_root=_tile_cache_root(artifact_root),
            maps_config=maps_config,
        )
    except OverlayAnimationEncoderUnavailableError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.RENDER_FAILED,
            TranslationKey.ERROR_OVERLAY_ANIMATION_ENCODER_UNAVAILABLE,
            "Animation overlay encoder is unavailable",
        )
    except OverlayAnimationEncodingError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.RENDER_FAILED,
            TranslationKey.ERROR_RENDER_FAILED,
            "Animation overlay encoding failed",
        )
    except ValueError:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.MISSING_METRIC,
            TranslationKey.ERROR_OVERLAY_ANIMATION_REQUIRES_ROUTE,
            "Animation overlay requires route and distance samples",
        )

    delivery_items: list[dict[str, object]] = []
    attachment_messages: list[OutgoingMessage] = []
    for artifact in artifacts:
        storage_path = f"artifacts/{artifact.filename}"
        storage_status = "not_written_in_skeleton"
        if artifact_root is not None:
            stored_path = write_bytes_under(artifact_root, artifact.filename, artifact.content)
            storage_path = str(stored_path)
            storage_status = "written"
        metadata = {
            **artifact.metadata,
            "channel_id": event.channel_id,
            "source_event_id": event.event_id,
            "storage_status": storage_status,
        }
        public_url = _publish_public_artifact_if_needed(artifact, public_artifacts)
        if public_url is not None:
            metadata["delivery"] = "public_url"
            metadata["public_url"] = public_url
        else:
            metadata["delivery"] = "discord_attachment"
        overlay_type = str(metadata.get("overlay_type", "overlay"))
        repositories.rendered_artifacts.add(
            RenderedArtifactRecord(
                artifact_id=f"{event.event_id}:animation-overlay:{overlay_type}",
                owner_user_id=event.user_id,
                workflow_trace_id=None,
                artifact_type="animation_overlay",
                filename=artifact.filename,
                content_type=artifact.content_type,
                storage_path=storage_path,
                created_at=event.created_at.isoformat(),
                metadata=metadata,
            )
        )
        delivery_items.append(
            {
                "overlay_type": overlay_type,
                "filename": artifact.filename,
                "url": public_url,
                "metadata": metadata,
            }
        )
        if public_url is not None:
            continue
        attachment_messages.append(
            OutgoingMessage(
                kind=OutgoingKind.FILE,
                filename=artifact.filename,
                content_type=artifact.content_type,
                content=artifact.content,
                metadata=metadata,
            )
        )
    summary = OutgoingMessage(
        kind=OutgoingKind.TEXT,
        localized_text=LocalizedText(
            key=TranslationKey.OVERLAY_ANIMATION_BUNDLE_CREATED,
            params=_overlay_bundle_message_params(workout, delivery_items),
        ),
        metadata={
            "chart_type": "animation_overlay",
            "delivery": "bundle_summary",
            "overlay_count": len(delivery_items),
            "overlays": tuple(item["overlay_type"] for item in delivery_items),
        },
    )
    if attachment_messages:
        return WorkflowResult(status=WorkflowStatus.SUCCESS, messages=(summary, *attachment_messages))
    return WorkflowResult(status=WorkflowStatus.SUCCESS, messages=(summary,))


def _overlay_bundle_message_params(workout: WorkoutRecord, items: list[dict[str, object]]) -> dict[str, object]:
    start_values = [
        float(metadata["start_km"])
        for item in items
        if isinstance(item.get("metadata"), dict)
        for metadata in (item["metadata"],)
        if metadata.get("start_km") is not None
    ]
    start_km = min(start_values) if start_values else 0.0
    lines = []
    for item in items:
        label = _overlay_label(str(item.get("overlay_type", "overlay")))
        target = item.get("url") or item.get("filename") or ""
        lines.append(f"{label}: {target}")
    return {
        "title": workout.title or workout.workout_id,
        "date": workout.local_date or (workout.start_time_local or workout.start_time_utc or "")[:10] or "",
        "start_km": f"{start_km:.2f}",
        "items": "\n".join(lines),
    }


def _overlay_label(overlay_type: str) -> str:
    if overlay_type == "route":
        return "Reitti"
    if overlay_type == "map":
        return "Kartta"
    if overlay_type == "hr":
        return "Syke"
    return overlay_type


def _publish_public_artifact_if_needed(
    artifact: VisualizationArtifact,
    public_artifacts: PublicArtifactsConfig | None,
) -> str | None:
    if public_artifacts is None or public_artifacts.path is None or not public_artifacts.base_url:
        return None
    if len(artifact.content) <= public_artifacts.max_discord_attachment_bytes:
        return None
    public_filename = Path(artifact.filename).name
    write_bytes_under(public_artifacts.path, public_filename, artifact.content)
    return f"{public_artifacts.base_url.rstrip('/')}/{public_filename}"


def _resolve_animation_workout(event: CanonicalEvent, repositories: RepositoryBundle) -> WorkoutRecord | None:
    selector = _tarkenne_value(event.text, "workout") or _tarkenne_value(event.text, "treeni")
    if selector:
        resolved = resolve_workout_selector(repositories, event.user_id, _animation_selector(selector), default="none")
        return resolved.workout if resolved.status == WorkoutReferenceStatus.MATCHED else None
    resolved = resolve_workout_selector(repositories, event.user_id, {"type": "active", "value": "", "count": None, "limit": None}, default="active")
    if resolved.status == WorkoutReferenceStatus.MATCHED:
        return resolved.workout
    resolved = resolve_workout_selector(repositories, event.user_id, {"type": "latest", "value": "", "count": None, "limit": None}, default="latest")
    return resolved.workout if resolved.status == WorkoutReferenceStatus.MATCHED else None


def _animation_selector(value: str) -> dict[str, object]:
    normalized = value.strip().lower()
    if normalized in {"active", "aktiivinen"}:
        return {"type": "active", "value": "", "count": None, "limit": None}
    if normalized in {"latest", "last", "viimeisin", "uusin"}:
        return {"type": "latest", "value": "", "count": None, "limit": None}
    return {"type": "id", "value": value.strip(), "count": None, "limit": None}


def _animation_request(text: str) -> OverlayAnimationRequest:
    overlay_types = _overlay_tarkenne_values(text)
    if not overlay_types:
        overlay_types = ("map",)
    has_dist = bool(_tarkenne_value(text, "dist"))
    start_km = _distance_tarkenne(
        text,
        "dist",
        default=_distance_tarkenne(text, "start", default=_distance_tarkenne(text, "distance", default=0.0)),
    )
    sync = _tarkenne_value(text, "sync").lower()
    real_time = has_dist or sync == "real"
    length_default = 60.0 if real_time else 5.0
    length_s = _duration_tarkenne(text, "duration", default=_duration_tarkenne(text, "length", default=length_default))
    view = _tarkenne_value(text, "view").lower()
    output_format = _tarkenne_value(text, "format").lower()
    map_layout = _tarkenne_value(text, "map_layout").lower() or "circle"
    hr_layout = _tarkenne_value(text, "hr_layout").lower() or "line"
    map_mode = _tarkenne_value(text, "map").lower()
    tail_mode = _tarkenne_value(text, "tail_mode").lower()
    has_fixed_tail = bool(_tarkenne_value(text, "tail"))
    route_position = _tarkenne_value(text, "route_position").lower()
    route_background = _tarkenne_value(text, "route_background").lower()
    normalized_map_layout = map_layout if map_layout in {"circle", "default"} else "circle"
    normalized_hr_layout = hr_layout if hr_layout in {"line"} else "line"
    normalized_map_mode = map_mode if map_mode in {"schematic", "tiles"} else ("tiles" if normalized_map_layout == "circle" else "schematic")
    normalized_tail_mode = tail_mode if tail_mode in {"time", "distance"} else ("distance" if has_fixed_tail else "time")
    normalized_route_position = route_position if route_position in {"left", "right", "center"} else "right"
    normalized_route_background = route_background if route_background in {"dim", "none"} else "dim"
    transparent = _boolean_tarkenne(text, "transparent", default=True) or _tarkenne_value(text, "background").lower() == "transparent"
    if not output_format:
        output_format = "mov" if transparent else "mp4"
    return OverlayAnimationRequest(
        start_km=start_km,
        window_km=max(0.05, _distance_tarkenne(text, "window", default=0.5)),
        length_s=_clamped_float(length_s, 1.0, 300.0 if real_time else 15.0),
        fps=int(_clamped_float(_numeric_tarkenne(text, "fps", default=10.0), 1.0, 20.0)),
        width=_render_size_tarkenne(text)[0],
        height=_render_size_tarkenne(text)[1],
        overlay_types=overlay_types,
        show_map="map" in overlay_types,
        show_speed=False,
        show_hr="hr" in overlay_types,
        sync="real" if real_time else "fit",
        view="local" if real_time and view not in {"segment", "full"} else (view or "segment"),
        radius_km=max(0.04, _distance_tarkenne(text, "radius", default=0.3)),
        tail_km=max(0.0, _distance_tarkenne(text, "tail", default=0.2)),
        tail_mode=normalized_tail_mode,
        tail_time_s=_clamped_float(_duration_tarkenne(text, "tail_time", default=30.0), 3.0, 180.0),
        tail_max_km=max(0.03, _distance_tarkenne(text, "tail_max", default=0.25)),
        lookahead_km=max(0.0, _distance_tarkenne(text, "lookahead", default=0.1)),
        auto_zoom=_boolean_tarkenne(text, "auto_zoom", default=True),
        radius_min_km=max(0.04, _distance_tarkenne(text, "radius_min", default=0.1)),
        tail_min_km=max(0.02, _distance_tarkenne(text, "tail_min", default=0.06)),
        auto_zoom_fast_pace_s_per_km=_pace_tarkenne(text, "auto_zoom_fast", default=240.0),
        auto_zoom_slow_pace_s_per_km=_pace_tarkenne(text, "auto_zoom_slow", default=540.0),
        auto_zoom_sample_s=_clamped_float(_duration_tarkenne(text, "auto_zoom_sample", default=20.0), 4.0, 60.0),
        output_format=output_format if output_format in {"gif", "webm", "mov", "mp4"} else ("mov" if transparent else "mp4"),
        transparent=transparent,
        map_layout=normalized_map_layout,
        hr_layout=normalized_hr_layout,
        map_mode=normalized_map_mode,
        compass=_boolean_tarkenne(text, "compass", default=normalized_map_layout == "circle"),
        map_style=_map_style_tarkenne(text),
        tile_alpha=_clamped_float(_numeric_tarkenne(text, "tile_alpha", default=0.9), 0.0, 1.0),
        route_position=normalized_route_position,
        route_size=int(_clamped_float(_numeric_tarkenne(text, "route_size", default=360.0), 120.0, 720.0)),
        route_background=normalized_route_background,
        route_tail=_boolean_tarkenne(text, "route_tail", default=True),
    )


def _overlay_tarkenne_values(text: str) -> tuple[str, ...]:
    value = _tarkenne_value(text, "overlay")
    if not value:
        return ()
    aliases = {
        "map": "map",
        "kartta": "map",
        "route": "route",
        "reitti": "route",
        "overview": "route",
        "hr": "hr",
        "syke": "hr",
        "heart": "hr",
        "heartrate": "hr",
        "heart-rate": "hr",
        "heart_rate": "hr",
    }
    values: list[str] = []
    for item in re.split(r"[,/]+", value.strip().lower().replace("_", "-")):
        normalized = aliases.get(item.strip())
        if normalized is not None and normalized not in values:
            values.append(normalized)
    return tuple(values)


def _tarkenne_value(text: str, key: str) -> str:
    match = re.search(rf"(?<!\w){re.escape(key)}\s*=\s*([^\s;]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _distance_tarkenne(text: str, key: str, *, default: float) -> float:
    value = _tarkenne_value(text, key)
    if not value:
        return default
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)(km|m)?", value.strip().lower())
    if match is None:
        return default
    amount = float(match.group(1).replace(",", "."))
    return amount / 1000.0 if match.group(2) == "m" else amount


def _duration_tarkenne(text: str, key: str, *, default: float) -> float:
    value = _tarkenne_value(text, key)
    if not value:
        return default
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)(s|sec|sek|min|m)?", value.strip().lower())
    if match is None:
        return default
    amount = float(match.group(1).replace(",", "."))
    return amount * 60.0 if match.group(2) in {"min", "m"} else amount


def _pace_tarkenne(text: str, key: str, *, default: float) -> float:
    value = _tarkenne_value(text, key)
    if not value:
        return default
    normalized = value.strip().lower().removesuffix("/km")
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", normalized)
    if match is not None:
        return float(int(match.group(1)) * 60 + int(match.group(2)))
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return default


def _numeric_tarkenne(text: str, key: str, *, default: float) -> float:
    value = _tarkenne_value(text, key)
    if not value:
        return default
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return default


def _boolean_tarkenne(text: str, key: str, *, default: bool) -> bool:
    value = _tarkenne_value(text, key).strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on", "kylla", "kyllä"}:
        return True
    if value in {"0", "false", "no", "off", "ei"}:
        return False
    return default


def _render_size_tarkenne(text: str) -> tuple[int, int]:
    value = _tarkenne_value(text, "size")
    match = re.fullmatch(r"(\d{2,4})x(\d{2,4})", value.lower()) if value else None
    if match is None:
        return (1280, 720)
    width = int(_clamped_float(float(match.group(1)), 240, 1280))
    height = int(_clamped_float(float(match.group(2)), 180, 720))
    return width, height


def _map_style_tarkenne(text: str) -> str:
    value = _tarkenne_value(text, "map_style") or _tarkenne_value(text, "style")
    normalized = value.strip().lower().replace("_", "-")
    aliases = {
        "dark": "streets-v2-dark",
        "streets-dark": "streets-v2-dark",
        "streets-v2-dark": "streets-v2-dark",
        "streets-v4-dark": "streets-v4-dark",
        "outdoor-dark": "outdoor-v2-dark",
        "outdoor-v2-dark": "outdoor-v2-dark",
        "outdoors-dark": "outdoor-v2-dark",
        "outdoor": "outdoor-v2",
        "outdoor-v2": "outdoor-v2",
        "outdoors": "outdoor-v2",
        "dataviz-dark": "dataviz-dark",
        "light": "dataviz-light",
        "dataviz-light": "dataviz-light",
        "dataviz": "dataviz",
        "streets": "streets-v4",
        "streets-v4": "streets-v4",
        "streets-v2": "streets-v2",
        "basic-dark": "basic-v2-dark",
        "basic-v2-dark": "basic-v2-dark",
        "basic": "basic-v2",
        "basic-v2": "basic-v2",
    }
    return aliases.get(normalized, "streets-v2-dark")


def _clamped_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _route_time_title_context(
    event: CanonicalEvent,
    resolved: ResolvedVisualizationRequest,
    points: tuple[WorkoutPointRecord, ...],
    *,
    repositories: RepositoryBundle,
    gateway: LLMGateway | None,
    weather_provider: WeatherProvider | None,
    language: SupportedLanguage,
) -> dict[str, object]:
    if not _route_map_can_show_estimate(resolved):
        return {"title_summary": "", "metadata": {}}
    target_feature = repositories.workout_estimate_features.get(resolved.workout.workout_id)
    history_features = repositories.workout_estimate_features.list_for_user(event.user_id, limit=100)
    history = repositories.workouts.list_for_user(event.user_id, limit=100)
    estimate = estimate_route_time_from_features(resolved.workout, target_feature, points, history_features, history)
    if estimate is None:
        return {"title_summary": "", "metadata": {}}
    target_date = ""
    activity_intent = "unknown"
    if gateway is not None:
        try:
            route_time_intent = interpret_route_time_estimate_intent(
                gateway,
                RouteTimeEstimateIntentInput(
                    user_text=event.text,
                    current_date=local_now(event.created_at).date().isoformat(),
                    timezone=DEFAULT_PERIOD_TIMEZONE,
                    compact_routing_context={
                        "active_workout_id": _active_workout_context(event, repositories).get("workout_id", ""),
                        "recent_workout_count": len(repositories.workouts.list_for_user(event.user_id, limit=20)),
                    },
                ),
            )
        except LLMGatewayError:
            route_time_intent = None
        if route_time_intent is not None and route_time_intent.is_route_time_estimate:
            target_date = route_time_intent.target_date
            activity_intent = route_time_intent.activity_intent
    weather_payload = build_route_time_weather_payload(
        estimate,
        target_feature,
        points,
        target_date=target_date,
        activity_intent=activity_intent,
        provider=weather_provider,
    )
    title_summary = format_route_time_title_summary(estimate, weather_payload, language=language.value)
    return {
        "title_summary": title_summary,
        "metadata": {
            "route_time_title_summary": title_summary,
            "route_time_estimate_s": round(estimate.estimate_s),
            "route_time_weather": weather_payload or {},
        },
    }


def _route_map_can_show_estimate(resolved: ResolvedVisualizationRequest) -> bool:
    intent = resolved.intent
    return (
        resolved.scope_type == "single_workout"
        and not _is_comparison_intent(intent)
        and intent.output_mode == "chart"
        and intent.chart_kind == "map"
        and "route" in intent.y_metrics
    )


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


def _backfill_waypoints_from_raw_gpx(
    resolved: ResolvedVisualizationRequest,
    repositories: RepositoryBundle,
) -> ResolvedVisualizationRequest:
    if resolved.scope_type != "single_workout":
        return resolved
    workout = _workout_with_backfilled_waypoints(resolved.workout, repositories)
    if workout == resolved.workout:
        return resolved
    return replace(
        resolved,
        workout=workout,
        workouts=tuple(workout if item.workout_id == workout.workout_id else item for item in resolved.workouts),
    )


def _workout_with_backfilled_waypoints(workout: WorkoutRecord, repositories: RepositoryBundle) -> WorkoutRecord:
    if _metadata_int(workout.metadata.get("waypoint_count")) <= 0 or not _needs_waypoint_backfill(workout.metadata.get("waypoints")):
        return workout
    if not workout.source_attachment_id:
        return workout
    attachment = repositories.attachments.get(workout.source_attachment_id)
    if attachment is None or not attachment.raw_path:
        return workout
    raw_path = Path(attachment.raw_path)
    if not raw_path.exists() or not raw_path.is_file():
        return workout
    try:
        parsed = parse_gpx(raw_path.read_bytes(), fallback_title=attachment.filename)
    except (GpxParseError, OSError):
        return workout
    waypoints = parsed.metadata.get("waypoints")
    if not isinstance(waypoints, list) or not waypoints:
        return workout
    updated = replace(workout, metadata={**workout.metadata, "waypoints": waypoints})
    repositories.workouts.update_derived_fields(updated)
    return updated


def _needs_waypoint_backfill(value: object) -> bool:
    if not isinstance(value, list) or not value:
        return True
    return any(isinstance(item, dict) and not any(item.get(key) for key in ("comment", "description", "type", "symbol")) for item in value)


def _metadata_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
    repositories: RepositoryBundle,
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
                    "active_workout": _active_workout_context(event, repositories),
                },
                previous_visualization=previous_visualization,
            ),
        )
        return _apply_visualization_modifiers(intent, event.text)
    raise LLMGatewayError("Visualization intent extraction requires an LLM gateway or structured command options")


def _apply_visualization_modifiers(intent: VisualizationIntent, text: str) -> VisualizationIntent:
    modifiers = _visualization_modifiers(text)
    negative_modifiers = _visualization_negative_modifiers(text)
    social_style = _social_style_from_text(
        text,
        modifiers,
        base=intent.social_style,
        enabled=intent.output_mode == "social_image",
    )
    if any(modifier in WAYPOINT_HIDE_MODIFIERS for modifier in negative_modifiers):
        social_style["waypoints"] = False
    if any(modifier in ELEVATION_OVERLAY_HIDE_MODIFIERS for modifier in negative_modifiers):
        social_style["elevation_overlay"] = False
    if any(modifier in ELEVATION_OVERLAY_SHOW_MODIFIERS for modifier in modifiers):
        social_style["elevation_overlay"] = True
    if any(modifier in ROUTE_DIRECTION_MODIFIERS for modifier in modifiers):
        social_style["direction_arrows"] = True
    if not modifiers and social_style == intent.social_style:
        return intent
    output_mode = "social_image" if any(modifier in SOCIAL_OUTPUT_MODIFIERS for modifier in modifiers) else intent.output_mode
    metric_map = SOCIAL_STAT_MODIFIER_METRICS if output_mode == "social_image" else VISUALIZATION_MODIFIER_METRICS
    extra_metrics = tuple(metric_map[modifier] for modifier in modifiers if modifier in metric_map)
    render_size = next((VISUALIZATION_ASPECT_SIZES[modifier] for modifier in modifiers if modifier in VISUALIZATION_ASPECT_SIZES), None)
    if any(modifier in SOCIAL_STYLE_PRESETS for modifier in modifiers):
        output_mode = "social_image"
    if output_mode != intent.output_mode:
        extra_metrics = tuple(dict.fromkeys(("route", *extra_metrics)))
    if not extra_metrics and render_size is None and output_mode == intent.output_mode and social_style == intent.social_style:
        return intent
    route_color_metric = intent.route_color_metric
    ignored_route_metrics: tuple[str, ...] = ()
    if output_mode == "social_image" and "route" in tuple(dict.fromkeys((*intent.y_metrics, *extra_metrics))):
        route_metrics = tuple(
            SOCIAL_ROUTE_COLOR_MODIFIER_METRICS[modifier]
            for modifier in modifiers
            if modifier in SOCIAL_ROUTE_COLOR_MODIFIER_METRICS
        )
        if route_metrics:
            route_color_metric = route_metrics[0]
            ignored_route_metrics = route_metrics[1:]
    elif intent.chart_kind == "map" and "route" in intent.y_metrics:
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
        chart_kind="map" if output_mode == "social_image" else intent.chart_kind,
        context_update=intent.context_update,
        route_color_metric=route_color_metric,
        route_color_ignored_metrics=ignored_route_metrics,
        render_width=render_size[0] if render_size is not None else intent.render_width,
        render_height=render_size[1] if render_size is not None else intent.render_height,
        output_mode=output_mode,
        social_style=social_style,
    )


def _social_route_error_key(intent: VisualizationIntent, exc: MissingPrimaryMetricError) -> TranslationKey | None:
    if intent.output_mode == "social_image" and exc.metric == "route":
        return TranslationKey.ERROR_SOCIAL_IMAGE_REQUIRES_ROUTE
    return None


def _visualization_modifiers(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(1).lower().replace("-", "_") for match in re.finditer(r"(?<!\w)\+([\w:-]+)", text)))


def _visualization_negative_modifiers(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(1).lower().replace("-", "_") for match in re.finditer(r"(?<!\w)-([\w:-]+)", text)))


def _social_style_from_text(
    text: str,
    modifiers: tuple[str, ...],
    *,
    base: dict[str, object],
    enabled: bool = False,
) -> dict[str, object]:
    style = _normalize_social_style(base)
    for modifier in modifiers:
        if modifier in SOCIAL_STYLE_PRESETS:
            style["preset"] = modifier
    style.update(_parse_social_style_block(text))
    if enabled or any(modifier in SOCIAL_OUTPUT_MODIFIERS or modifier in SOCIAL_STYLE_PRESETS for modifier in modifiers) or style:
        style.update(_parse_inline_social_style_tokens(text))
    return style


def _parse_social_style_block(text: str) -> dict[str, object]:
    style: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("tyyli:"):
            style.update(_parse_social_style_tokens(stripped.split(":", 1)[1]))
        elif lowered.startswith("style:"):
            style.update(_parse_social_style_tokens(stripped.split(":", 1)[1]))
    return style


def _parse_inline_social_style_tokens(text: str) -> dict[str, object]:
    lines = [
        line
        for line in text.splitlines()
        if not line.strip().lower().startswith(("tyyli:", "style:"))
    ]
    return _parse_social_style_tokens(" ".join(lines))


def _parse_social_style_tokens(value: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for token in re.split(r"[\s;]+", value.strip()):
        if not token or "=" not in token:
            continue
        raw_key, raw_value = token.split("=", 1)
        key = SOCIAL_STYLE_ALIASES.get(raw_key.strip().lower().replace("-", "_"), raw_key.strip().lower().replace("-", "_"))
        normalized = _normalize_social_style_value(key, raw_value.strip())
        if normalized is not None:
            parsed[key] = normalized
    return parsed


def _normalize_social_style(style: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for raw_key, raw_value in style.items():
        key = SOCIAL_STYLE_ALIASES.get(str(raw_key).strip().lower().replace("-", "_"), str(raw_key).strip().lower().replace("-", "_"))
        value = _normalize_social_style_value(key, raw_value)
        if value is not None:
            normalized[key] = value
    return normalized


def _normalize_social_style_value(key: str, value: object) -> object | None:
    if value in (None, ""):
        return None
    if key == "preset":
        text = str(value).strip().lower().replace("-", "_")
        return text if text in SOCIAL_STYLE_PRESETS else None
    if key in SOCIAL_STYLE_ENUMS:
        text = str(value).strip().lower().replace("-", "_")
        if key == "crop" and _is_crop_point(text):
            return text
        return text if text in SOCIAL_STYLE_ENUMS[key] else None
    if key in SOCIAL_STYLE_BOOLEAN_KEYS:
        return _style_bool(value)
    if key in SOCIAL_STYLE_INTEGER_RANGES:
        integer = _style_int(value)
        if integer is None:
            return None
        lower, upper = SOCIAL_STYLE_INTEGER_RANGES[key]
        return max(lower, min(upper, integer))
    if key in SOCIAL_STYLE_COLOR_KEYS:
        text = str(value).strip().lower()
        if text in SOCIAL_STYLE_COLOR_NAMES or re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            return text
    return None


def _is_crop_point(value: str) -> bool:
    match = re.fullmatch(r"(\d{1,3}),(\d{1,3})", value)
    if match is None:
        return False
    x_value, y_value = int(match.group(1)), int(match.group(2))
    return 0 <= x_value <= 100 and 0 <= y_value <= 100


def _style_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "kylla", "kyllä"}:
        return True
    if text in {"0", "false", "no", "off", "ei"}:
        return False
    return None


def _style_int(value: object) -> int | None:
    try:
        return int(str(value).strip().removesuffix("%"))
    except ValueError:
        return None


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
        output_mode=str(options.get("output_mode") or "chart"),
        social_style=options.get("social_style") if isinstance(options.get("social_style"), dict) else {},
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


def _active_workout_context(event: CanonicalEvent, repositories: RepositoryBundle) -> dict[str, object]:
    workout = repositories.active_workouts.get(event.user_id)
    if workout is None:
        return {}
    points = repositories.workout_streams.list_points(workout.workout_id)
    return {
        "workout_id": workout.workout_id,
        "title": workout.title,
        "kind": workout.kind,
        "primary_kind": workout.primary_kind,
        "distance_km": workout.distance_km,
        "local_date": workout.local_date,
        "has_route_points": any(point.latitude is not None and point.longitude is not None for point in points),
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
        "output_mode": intent.output_mode,
        "social_style": intent.social_style,
    }


def _social_background_image(event: CanonicalEvent) -> bytes | None:
    for attachment in event.attachments:
        if not _is_supported_image_attachment(attachment.filename, attachment.content_type):
            continue
        content = attachment.metadata.get("content")
        if isinstance(content, bytes):
            return content
    return None


def _is_supported_image_attachment(filename: str, content_type: str) -> bool:
    return filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) or content_type.split(";", 1)[0].strip().lower() in {
        "image/jpeg",
        "image/png",
        "image/webp",
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
            "grade": "jyrkkyys",
            "pace_s_per_km": "vauhti",
        }
        return labels.get(metric, metric)
    labels = {
        "heart_rate_bpm": "heart rate",
        "elevation_m": "elevation",
        "grade": "grade",
        "pace_s_per_km": "pace",
    }
    return labels.get(metric, metric)


def _resolve_workout(
    event: CanonicalEvent,
    intent: VisualizationIntent,
    repositories: RepositoryBundle,
) -> WorkoutReferenceResolution:
    selector = intent.workout_selector
    resolved = resolve_workout_selector(repositories, event.user_id, selector, default="active")
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
    return comparison in {"recent", "compare", "comparison", "previous", "previous_period", "multi", "multiple"}


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
