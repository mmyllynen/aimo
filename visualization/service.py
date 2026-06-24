from __future__ import annotations

import math
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image

from core.config import MapsConfig
from core.i18n import SupportedLanguage
from llm.operations import VisualizationIntent
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from visualization.datasets import Dataset, DatasetManifest, DatasetRequest, dataset_request_from_metrics, resolve_datasets
from visualization.metrics import (
    clean_metric_series,
    metric_direction,
    metric_invert_axis,
    metric_tick_format,
    metric_unit,
    visual_domain,
)
from visualization.render import (
    Bar,
    BarChart,
    DEFAULT_RENDER_HEIGHT,
    DEFAULT_RENDER_WIDTH,
    LineChart,
    LinePanel,
    MultiPanelLineChart,
    PieChart,
    PieSlice,
    RouteMap,
    RouteMapTile,
    RouteElevationProfile,
    RouteElevationSample,
    RoutePoint,
    RoutePolyline,
    RouteWaypoint,
    RenderSeries,
    SocialImage,
    SocialImageStat,
    SocialImageStyle,
    route_map_viewport,
)
from visualization.renderer import ChartType, resolve_renderer
from visualization.tiles import TileCoord, TileFetchConfig, TileFetchError, fetch_tiles
from visualization.specs import (
    MissingRenderableDataError,
    VisualizationValidationIssue,
    VisualizationSpec,
    VisualizationSpecError,
    allowed_visualization_primitives,
    compile_visualization_spec,
    visualization_validation_issue,
)


@dataclass(frozen=True)
class VisualizationArtifact:
    content: bytes
    filename: str
    content_type: str
    rendered_metrics: tuple[str, ...]
    missing_metrics: tuple[str, ...]
    scaled_metrics: tuple[str, ...]
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class VisualizationValidationContext:
    dataset_manifest: dict[str, Any]
    validation_errors: tuple[dict[str, Any], ...]
    allowed_primitives: dict[str, Any]


class VisualizationError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedSpec:
    content: bytes
    chart_type: ChartType
    renderer: str


class MissingPrimaryMetricError(VisualizationError):
    def __init__(self, metric: str) -> None:
        self.metric = metric
        super().__init__(metric)


ROUTE_COLOR_MODE_METRIC = "metric"
ROUTE_COLOR_MODE_ELEVATION_GRADE = "elevation_grade"


class VisualizationSpecInvalidError(VisualizationError):
    def __init__(self, reason: str, *, validation_errors: tuple[dict[str, Any], ...] = ()) -> None:
        self.reason = reason
        self.validation_errors = validation_errors
        super().__init__(reason)


def render_workout_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...] = (),
    comparison_workouts: tuple[WorkoutRecord, ...] = (),
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
    social_background_image: bytes | None = None,
    route_time_title_summary: str = "",
    route_time_metadata: dict[str, Any] | None = None,
) -> VisualizationArtifact:
    if _is_social_image_intent(intent):
        return _render_social_image_visualization(
            workout,
            points,
            intent,
            filename_prefix=workout.workout_id,
            tile_cache_root=tile_cache_root,
            maps_config=maps_config,
            language=language,
            background_image=social_background_image,
        )
    if _is_route_map_intent(intent):
        return _render_route_map_visualization(
            workout,
            points,
            intent,
            filename_prefix=workout.workout_id,
            tile_cache_root=tile_cache_root,
            maps_config=maps_config,
            language=language,
            route_time_title_summary=route_time_title_summary,
            route_time_metadata=route_time_metadata,
        )
    request = dataset_request_from_metrics(
        x_metric=intent.x_metric,
        y_metrics=intent.y_metrics,
        transforms=intent.transforms,
        comparison=_is_comparison_intent(intent),
        chart_kind=intent.chart_kind,
    )
    manifest = resolve_datasets(
        request,
        points=points,
        heart_rate_zones=heart_rate_zones,
        workout=workout,
        comparison_workouts=comparison_workouts,
    )
    try:
        spec = compile_visualization_spec(request, manifest)
    except MissingRenderableDataError as exc:
        raise MissingPrimaryMetricError(exc.column_id) from exc
    except VisualizationSpecError as exc:
        issue = visualization_validation_issue(exc, manifest)
        raise VisualizationSpecInvalidError(type(exc).__name__, validation_errors=(issue.to_model_error(),)) from exc

    dataset = manifest.dataset(spec.x.dataset_id)
    if dataset is None:
        raise VisualizationSpecInvalidError("DatasetNotFound")
    layout_mode = _effective_layout_mode(intent.layout_mode, spec)
    render_size = _render_size(intent)
    rendered = _render_spec(workout, spec, dataset, layout_mode=layout_mode, render_size=render_size, language=language)
    return VisualizationArtifact(
        content=rendered.content,
        filename=f"{workout.workout_id}-{spec.output_filename_suffix}.png",
        content_type="image/png",
        rendered_metrics=tuple(encoding.column_id for encoding in spec.y),
        missing_metrics=(),
        scaled_metrics=_scaled_metrics(spec, layout_mode),
        metadata={"renderer": rendered.renderer, "chart_type": rendered.chart_type, "render_width": render_size[0], "render_height": render_size[1]},
    )


def render_period_visualization(
    title_workout: WorkoutRecord,
    intent: VisualizationIntent,
    *,
    manifest: DatasetManifest,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> VisualizationArtifact:
    if _is_route_map_intent(intent):
        route_points = _route_points_from_manifest(manifest)
        route_labels = _route_labels_from_manifest(manifest)
        return _render_route_map_visualization(
            title_workout,
            route_points,
            intent,
            filename_prefix=title_workout.workout_id,
            tile_cache_root=tile_cache_root,
            maps_config=maps_config,
            language=language,
            route_labels=route_labels,
        )
    request = _dataset_request(intent, comparison=False)
    return _render_from_manifest(title_workout, intent, request, manifest, filename_prefix=title_workout.workout_id, language=language)


def visualization_validation_context(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...] = (),
    comparison_workouts: tuple[WorkoutRecord, ...] = (),
) -> VisualizationValidationContext:
    request = dataset_request_from_metrics(
        x_metric=intent.x_metric,
        y_metrics=intent.y_metrics,
        transforms=intent.transforms,
        comparison=_is_comparison_intent(intent),
        chart_kind=intent.chart_kind,
    )
    manifest = resolve_datasets(
        request,
        points=points,
        heart_rate_zones=heart_rate_zones,
        workout=workout,
        comparison_workouts=comparison_workouts,
    )
    issues: tuple[VisualizationValidationIssue, ...] = ()
    try:
        compile_visualization_spec(request, manifest)
    except VisualizationSpecError as exc:
        issues = (visualization_validation_issue(exc, manifest),)
    return VisualizationValidationContext(
        dataset_manifest=manifest.to_model_manifest(),
        validation_errors=tuple(issue.to_model_error() for issue in issues),
        allowed_primitives=allowed_visualization_primitives(),
    )


def period_visualization_validation_context(
    title_workout: WorkoutRecord,
    intent: VisualizationIntent,
    *,
    manifest: DatasetManifest,
) -> VisualizationValidationContext:
    request = _dataset_request(intent, comparison=False)
    issues: tuple[VisualizationValidationIssue, ...] = ()
    try:
        compile_visualization_spec(request, manifest)
    except VisualizationSpecError as exc:
        issues = (visualization_validation_issue(exc, manifest),)
    return VisualizationValidationContext(
        dataset_manifest=manifest.to_model_manifest(),
        validation_errors=tuple(issue.to_model_error() for issue in issues),
        allowed_primitives=allowed_visualization_primitives(),
    )


def _dataset_request(intent: VisualizationIntent, *, comparison: bool) -> DatasetRequest:
    return dataset_request_from_metrics(
        x_metric=intent.x_metric,
        y_metrics=intent.y_metrics,
        transforms=intent.transforms,
        comparison=comparison,
        chart_kind=intent.chart_kind,
    )


def _render_from_manifest(
    workout: WorkoutRecord,
    intent: VisualizationIntent,
    request: DatasetRequest,
    manifest: DatasetManifest,
    *,
    filename_prefix: str,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> VisualizationArtifact:
    try:
        spec = compile_visualization_spec(request, manifest)
    except MissingRenderableDataError as exc:
        raise MissingPrimaryMetricError(exc.column_id) from exc
    except VisualizationSpecError as exc:
        issue = visualization_validation_issue(exc, manifest)
        raise VisualizationSpecInvalidError(type(exc).__name__, validation_errors=(issue.to_model_error(),)) from exc

    dataset = manifest.dataset(spec.x.dataset_id)
    if dataset is None:
        raise VisualizationSpecInvalidError("DatasetNotFound")
    layout_mode = _effective_layout_mode(intent.layout_mode, spec)
    render_size = _render_size(intent)
    rendered = _render_spec(workout, spec, dataset, layout_mode=layout_mode, render_size=render_size, language=language)
    return VisualizationArtifact(
        content=rendered.content,
        filename=f"{filename_prefix}-{spec.output_filename_suffix}.png",
        content_type="image/png",
        rendered_metrics=tuple(encoding.column_id for encoding in spec.y),
        missing_metrics=(),
        scaled_metrics=_scaled_metrics(spec, layout_mode),
        metadata={"renderer": rendered.renderer, "chart_type": rendered.chart_type, "render_width": render_size[0], "render_height": render_size[1]},
    )


def _is_route_map_intent(intent: VisualizationIntent) -> bool:
    return intent.chart_kind == "map" and "route" in intent.y_metrics


def _is_social_image_intent(intent: VisualizationIntent) -> bool:
    return intent.output_mode == "social_image"


def _render_size(intent: VisualizationIntent) -> tuple[int, int]:
    if intent.render_width > 0 and intent.render_height > 0:
        return intent.render_width, intent.render_height
    return DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT


def _social_render_size(intent: VisualizationIntent) -> tuple[int, int]:
    if intent.render_width > 0 and intent.render_height > 0:
        return intent.render_width, intent.render_height
    return 1080, 1080


def _render_social_image_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    filename_prefix: str,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
    background_image: bytes | None = None,
) -> VisualizationArtifact:
    route_color_metric = intent.route_color_metric if _is_route_color_metric_supported(intent.route_color_metric) else ""
    route_color_mode = _route_color_mode(route_color_metric)
    routes = _route_polylines(
        points,
        workouts_by_id={workout.workout_id: workout},
        route_color_metric=route_color_metric,
        route_color_mode=route_color_mode,
    )
    if not routes:
        raise MissingPrimaryMetricError("route")
    color_status = _route_color_status(routes, route_color_metric=route_color_metric)
    active_color_metric = route_color_metric if color_status == "ok" else ""
    active_color_mode = route_color_mode if active_color_metric else ROUTE_COLOR_MODE_METRIC
    color_domain = _route_color_domain(routes, active_color_metric) if active_color_metric else None
    render_size = _social_render_size(intent)
    requested_attachment_background = background_image is not None
    if background_image is not None and not _is_decodable_image(background_image):
        background_image = None
    tile_data: dict[str, Any] | None = None
    map_background: RouteMap | None = None
    if background_image is None:
        tile_data = _route_tiles(
            routes,
            tile_cache_root,
            maps_config=maps_config,
            width=render_size[0],
            height=render_size[1],
            margin_ratio=0.03,
            safe_rect=(24, 24, render_size[0] - 24, render_size[1] - 24),
        )
        map_background = RouteMap(
            title=workout.title,
            subtitle="",
            routes=routes,
            tiles=tile_data["tiles"],
            tile_zoom=tile_data["tile_zoom"],
            tile_size=tile_data["tile_size"],
            attribution=tile_data["attribution"],
            x_domain=tile_data["x_domain"],
            y_domain=tile_data["y_domain"],
            width=render_size[0],
            height=render_size[1],
        )
    renderer = resolve_renderer("social_image")
    rendered = renderer.render_social_image_png(
        SocialImage(
            title=workout.title,
            routes=routes,
            stats=_social_stats(workout, intent, language=language),
            background_image=background_image,
            map_background=map_background,
            style=_social_image_style(intent),
            color_domain=color_domain,
            color_direction=metric_direction(active_color_metric) if active_color_metric else "ascending",
            width=render_size[0],
            height=render_size[1],
        )
    )
    metadata = {
        "renderer": renderer.name,
        "chart_type": "social_image",
        "output_mode": "social_image",
        "render_width": render_size[0],
        "render_height": render_size[1],
        "social_background": "attachment" if background_image is not None else "map",
        "social_background_requested": "attachment" if requested_attachment_background else "map",
        "social_background_status": "ok" if background_image is not None or not requested_attachment_background else "invalid_image_fallback_to_map",
        "social_layout_version": "2",
        "social_style": intent.social_style,
        "social_route_color_metric": active_color_metric,
        "social_route_color_mode": active_color_mode,
        "social_route_color_status": color_status,
        "social_route_color_domain": color_domain or (),
    }
    if tile_data is not None:
        metadata.update(tile_data["metadata"])
    return VisualizationArtifact(
        content=rendered,
        filename=f"{filename_prefix}-social-image.png",
        content_type="image/png",
        rendered_metrics=tuple(_social_metric_selection(intent)),
        missing_metrics=(),
        scaled_metrics=(),
        metadata=metadata,
    )


def _social_image_style(intent: VisualizationIntent) -> SocialImageStyle:
    style = _social_style_preset(str(intent.social_style.get("preset", "") or ""))
    overrides = {key: value for key, value in intent.social_style.items() if key != "preset"}
    if not overrides:
        return style
    return SocialImageStyle(
        preset=style.preset,
        background_crop=str(overrides.get("crop", style.background_crop)),
        background_dim=int(overrides.get("dim", style.background_dim)),
        background_filter=str(overrides.get("filter", style.background_filter)),
        route_color=str(overrides.get("route", style.route_color)),
        route_size=str(overrides.get("route_size", style.route_size)),
        route_shadow=bool(overrides.get("route_shadow", style.route_shadow)),
        route_markers=bool(overrides.get("markers", style.route_markers)),
        title_position=str(overrides.get("title", style.title_position)),
        title_align=str(overrides.get("title_align", style.title_align)),
        stats_position=str(overrides.get("stats", style.stats_position)),
        panel_style=str(overrides.get("panel", style.panel_style)),
        text_color=str(overrides.get("text", style.text_color)),
        accent_color=str(overrides.get("accent", style.accent_color)),
        font=str(overrides.get("font", style.font)),
        background_blur=int(overrides.get("blur", style.background_blur)),
        route_position=str(overrides.get("route_pos", style.route_position)),
        stats_style=str(overrides.get("stats_style", style.stats_style)),
    )


def _social_style_preset(value: str) -> SocialImageStyle:
    preset = value.strip().lower().replace("-", "_")
    if preset == "minimal":
        return SocialImageStyle(
            preset="minimal",
            background_dim=24,
            route_size="normal",
            route_shadow=False,
            title_position="bottom",
            stats_position="hide",
            panel_style="none",
            text_color="auto",
        )
    if preset == "poster":
        return SocialImageStyle(
            preset="poster",
            background_dim=42,
            background_filter="vivid",
            route_color="white",
            route_size="huge",
            title_position="bottom",
            stats_position="right",
            panel_style="dark",
            font="bold",
        )
    if preset == "routeonly":
        return SocialImageStyle(
            preset="routeonly",
            title_position="hide",
            stats_position="hide",
            panel_style="none",
            route_color="white",
            route_size="large",
        )
    if preset == "data":
        return SocialImageStyle(
            preset="data",
            background_dim=36,
            route_size="normal",
            title_position="top",
            stats_position="right",
            panel_style="dark",
            stats_style="stacked",
        )
    if preset == "photo":
        return SocialImageStyle(
            preset="photo",
            background_dim=18,
            route_color="white",
            route_size="normal",
            panel_style="none",
            stats_position="bottom",
        )
    return SocialImageStyle(preset="classic" if preset == "classic" else "")


def _is_decodable_image(content: bytes) -> bool:
    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
        return True
    except OSError:
        return False


def _render_route_map_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    filename_prefix: str,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
    route_labels: dict[str, str] | None = None,
    route_time_title_summary: str = "",
    route_time_metadata: dict[str, Any] | None = None,
) -> VisualizationArtifact:
    workouts_by_id = {workout.workout_id: workout}
    route_color_metric = intent.route_color_metric if _is_route_color_metric_supported(intent.route_color_metric) else ""
    route_color_mode = _route_color_mode(route_color_metric)
    routes = _route_polylines(
        points,
        workouts_by_id=workouts_by_id,
        route_labels=route_labels,
        route_color_metric=route_color_metric,
        route_color_mode=route_color_mode,
    )
    if not routes:
        raise MissingPrimaryMetricError("route")
    render_size = _render_size(intent)
    color_status = _route_color_status(routes, route_color_metric=route_color_metric)
    active_color_metric = route_color_metric if color_status == "ok" else ""
    active_color_mode = route_color_mode if active_color_metric else ROUTE_COLOR_MODE_METRIC
    color_domain = _route_color_domain(routes, active_color_metric) if active_color_metric else None
    waypoint_count = len(_route_waypoints_from_metadata(workout))
    waypoints = _route_waypoints(workout, routes) if _show_waypoints(intent) and len(routes) == 1 else ()
    waypoint_status = _waypoint_status(waypoint_count, waypoints, routes, intent)
    elevation_profile = _route_elevation_profile(points, routes, intent)
    elevation_status = _elevation_overlay_status(elevation_profile, routes, intent)
    chart = RouteMap(
        title=_route_map_title(workout.title, language=language),
        subtitle=_route_chart_subtitle(workout, language=language, estimate_summary=route_time_title_summary),
        routes=routes,
        waypoints=waypoints,
        elevation_profile=elevation_profile,
        legend_title=_route_legend_title(routes, language=language),
        color_metric_label=_route_color_metric_label(active_color_metric, language=language) if active_color_metric else "",
        color_domain=color_domain,
        color_tick_format=metric_tick_format(active_color_metric) if active_color_metric else "number",
        color_direction=metric_direction(active_color_metric) if active_color_metric else "ascending",
        color_mode=active_color_mode,
        show_direction=_show_route_direction(intent),
        width=render_size[0],
        height=render_size[1],
    )
    tile_data = _route_tiles(
        routes,
        tile_cache_root,
        maps_config=maps_config,
        width=chart.width,
        height=chart.height,
        waypoints=waypoints,
        safe_rect=_route_map_safe_rect(chart.width, chart.height, elevation_profile),
    )
    renderer = resolve_renderer("route")
    rendered = renderer.render_route_map_png(
        RouteMap(
            title=chart.title,
            subtitle=chart.subtitle,
            legend_title=chart.legend_title,
            color_metric_label=chart.color_metric_label,
            color_domain=chart.color_domain,
            color_tick_format=chart.color_tick_format,
            color_direction=chart.color_direction,
            color_mode=chart.color_mode,
            show_direction=chart.show_direction,
            routes=routes,
            waypoints=waypoints,
            elevation_profile=elevation_profile,
            tiles=tile_data["tiles"],
            tile_zoom=tile_data["tile_zoom"],
            tile_size=tile_data["tile_size"],
            attribution=tile_data["attribution"],
            x_domain=tile_data["x_domain"],
            y_domain=tile_data["y_domain"],
            width=render_size[0],
            height=render_size[1],
        )
    )
    metadata = {
        **tile_data["metadata"],
        "renderer": renderer.name,
        "chart_type": "route",
        "render_width": chart.width,
        "render_height": chart.height,
        "route_color_metric": active_color_metric,
        "route_color_ignored_metrics": intent.route_color_ignored_metrics,
        "route_color_status": color_status,
        "route_color_domain": color_domain or (),
        "route_color_tick_format": chart.color_tick_format,
        "route_color_direction": chart.color_direction,
        "route_color_mode": chart.color_mode,
        "route_direction_arrows": chart.show_direction,
        "waypoint_count": waypoint_count,
        "waypoints_rendered": len(waypoints),
        "waypoint_status": waypoint_status,
        "elevation_overlay_status": elevation_status,
        "elevation_overlay_min_m": _elevation_min(elevation_profile),
        "elevation_overlay_max_m": _elevation_max(elevation_profile),
    }
    if route_time_metadata:
        metadata.update(route_time_metadata)
    return VisualizationArtifact(
        content=rendered,
        filename=f"{filename_prefix}-route-map.png",
        content_type="image/png",
        rendered_metrics=("route", active_color_metric) if active_color_metric else ("route",),
        missing_metrics=(),
        scaled_metrics=(),
        metadata=metadata,
    )


def _route_tiles(
    routes: tuple[RoutePolyline, ...],
    tile_cache_root: Path | None,
    *,
    waypoints: tuple[RouteWaypoint, ...] = (),
    maps_config: MapsConfig | None = None,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
    margin_ratio: float = 0.06,
    safe_rect: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    viewport = route_map_viewport(routes, waypoints=waypoints, width=width, height=height, margin_ratio=margin_ratio, safe_rect=safe_rect)
    base_payload = {
        "x_domain": viewport.x_domain,
        "y_domain": viewport.y_domain,
    }
    if tile_cache_root is None:
        return {
            **base_payload,
            "tiles": (),
            "tile_zoom": None,
            "tile_size": 256,
            "attribution": "",
            "metadata": {"map_background": "plain", "tile_status": "disabled"},
        }
    providers = _tile_provider_configs(tile_cache_root, maps_config)
    for provider in providers:
        rendered = _fetch_route_tiles_for_provider(routes, viewport, base_payload, provider, width=width)
        if rendered["metadata"].get("tile_status") == "ok":
            return rendered
    return rendered if providers else {
        **base_payload,
        "tiles": (),
        "tile_zoom": None,
        "tile_size": 256,
        "attribution": "",
        "metadata": {"map_background": "plain", "tile_status": "no_tile_provider"},
    }


def _route_map_safe_rect(
    width: int,
    height: int,
    elevation_profile: RouteElevationProfile | None,
) -> tuple[int, int, int, int] | None:
    if elevation_profile is None:
        return None
    overlay_height = 220
    overlay_bottom_margin = 14
    return 48, 156, width - 48, max(156 + 64, height - overlay_height - overlay_bottom_margin - 24)


@dataclass(frozen=True)
class TileProviderConfig:
    name: str
    background: str
    attribution: str
    tile_size: int
    config: TileFetchConfig


def _tile_provider_configs(tile_cache_root: Path, maps_config: MapsConfig | None) -> tuple[TileProviderConfig, ...]:
    providers = []
    if maps_config is not None and maps_config.provider == "maptiler" and maps_config.maptiler_api_key:
        map_id = maps_config.maptiler_map_id
        providers.append(
            TileProviderConfig(
                name="maptiler",
                background="maptiler_tiles",
                attribution="MapTiler / OpenStreetMap contributors",
                tile_size=512,
                config=TileFetchConfig(
                    cache_root=tile_cache_root.parent / "maptiler_tiles" / map_id,
                    url_template=f"https://api.maptiler.com/maps/{map_id}/{{z}}/{{x}}/{{y}}.png?key={maps_config.maptiler_api_key}",
                    user_agent="AimoRoutePlotter/0.1",
                    timeout_s=maps_config.timeout_s,
                ),
            )
        )
    providers.append(
        TileProviderConfig(
            name="openstreetmap",
            background="osm",
            attribution="© OpenStreetMap contributors",
            tile_size=256,
            config=TileFetchConfig(cache_root=tile_cache_root),
        )
    )
    return tuple(providers)


def _fetch_route_tiles_for_provider(
    routes: tuple[RoutePolyline, ...],
    viewport,
    base_payload: dict[str, Any],
    provider: TileProviderConfig,
    *,
    width: int,
) -> dict[str, Any]:
    del routes
    config = provider.config
    preferred_zoom = _preferred_tile_zoom(viewport.x_domain, viewport.y_domain, width=width, tile_size=provider.tile_size, config=config)
    for zoom in range(preferred_zoom, config.min_zoom - 1, -1):
        coords = _tile_coords_for_viewport(viewport.x_domain, viewport.y_domain, zoom)
        if len(coords) <= config.max_tiles:
            try:
                result = fetch_tiles(coords, config)
            except TileFetchError as exc:
                return {
                    **base_payload,
                    "tiles": (),
                    "tile_zoom": None,
                    "tile_size": provider.tile_size,
                    "attribution": "",
                    "metadata": {"map_background": "plain", "tile_provider": provider.name, "tile_status": "fetch_failed", "tile_error": str(exc)},
                }
            return {
                **base_payload,
                "tiles": tuple(RouteMapTile(coord=tile.coord, content=tile.content) for tile in result.tiles),
                "tile_zoom": zoom,
                "tile_size": provider.tile_size,
                "attribution": provider.attribution,
                "metadata": {
                    "map_background": provider.background,
                    "tile_status": "ok",
                    "tile_provider": provider.name,
                    "tile_attribution": provider.attribution,
                    "tile_zoom": zoom,
                    "tile_size": provider.tile_size,
                    "tile_count": len(result.tiles),
                    "tile_sources": [tile.source for tile in result.tiles],
                    "route_overlay": "aimo",
                },
            }
    return {
        **base_payload,
        "tiles": (),
        "tile_zoom": None,
        "tile_size": provider.tile_size,
        "attribution": "",
        "metadata": {"map_background": "plain", "tile_provider": provider.name, "tile_status": "too_many_tiles"},
    }


def _preferred_tile_zoom(x_domain: tuple[float, float], y_domain: tuple[float, float], *, width: int, tile_size: int = 256, config: TileFetchConfig) -> int:
    domain_width = max(x_domain[1] - x_domain[0], 0.000001)
    raw_zoom = math.log2(width / (domain_width * float(tile_size)))
    return max(config.min_zoom, min(config.max_zoom, math.ceil(raw_zoom)))


def _tile_coords_for_viewport(x_domain: tuple[float, float], y_domain: tuple[float, float], zoom: int) -> tuple[TileCoord, ...]:
    n = 2**zoom
    x_min = max(0, min(n - 1, math.floor(x_domain[0] * n)))
    x_max = max(0, min(n - 1, math.floor(max(x_domain[1] * n - 1e-12, 0))))
    y_min = max(0, min(n - 1, math.floor(y_domain[0] * n)))
    y_max = max(0, min(n - 1, math.floor(max(y_domain[1] * n - 1e-12, 0))))
    return tuple(TileCoord(z=zoom, x=x, y=y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1))


def _route_polylines(
    points: tuple[WorkoutPointRecord, ...],
    *,
    workouts_by_id: dict[str, WorkoutRecord] | None = None,
    route_labels: dict[str, str] | None = None,
    route_color_metric: str = "",
    route_color_mode: str = ROUTE_COLOR_MODE_METRIC,
) -> tuple[RoutePolyline, ...]:
    workouts_by_id = workouts_by_id or {}
    route_labels = route_labels or {}
    grouped: dict[str, list[WorkoutPointRecord]] = {}
    for point in points:
        if point.latitude is None or point.longitude is None:
            continue
        grouped.setdefault(point.workout_id, []).append(point)
    routes = []
    for workout_id, route_points in grouped.items():
        if len(route_points) >= 2:
            color_values = _route_metric_values(route_points, route_color_metric, route_color_mode=route_color_mode)
            routes.append(
                RoutePolyline(
                    label=route_labels.get(workout_id) or _route_label(workouts_by_id.get(workout_id), workout_id),
                    points=tuple(
                        RoutePoint(
                            latitude=float(point.latitude),
                            longitude=float(point.longitude),
                            color_value=color_value,
                        )
                        for point, color_value in zip(route_points, color_values, strict=True)
                    ),
                    color_metric=route_color_metric,
                    color_mode=route_color_mode,
                )
            )
    return tuple(routes)


def _show_waypoints(intent: VisualizationIntent) -> bool:
    return intent.social_style.get("waypoints") is not False


def _show_elevation_overlay(intent: VisualizationIntent) -> bool:
    return intent.social_style.get("elevation_overlay") is not False


def _show_route_direction(intent: VisualizationIntent) -> bool:
    return intent.social_style.get("direction_arrows") is True


def _route_waypoints(workout: WorkoutRecord, routes: tuple[RoutePolyline, ...]) -> tuple[RouteWaypoint, ...]:
    if len(routes) != 1:
        return ()
    metadata_waypoints = _route_waypoints_from_metadata(workout)
    distances = _waypoint_distances_from_start(metadata_waypoints, routes[0])
    waypoints = tuple(
        RouteWaypoint(
            latitude=waypoint.latitude,
            longitude=waypoint.longitude,
            label=waypoint.label,
            waypoint_type=waypoint.waypoint_type,
            distance_km=distance_km,
        )
        for waypoint, distance_km in zip(metadata_waypoints, distances, strict=True)
    )
    return tuple(sorted(waypoints, key=lambda waypoint: waypoint.distance_km if waypoint.distance_km is not None else float("inf")))


def _route_elevation_profile(
    points: tuple[WorkoutPointRecord, ...],
    routes: tuple[RoutePolyline, ...],
    intent: VisualizationIntent,
) -> RouteElevationProfile | None:
    if not _show_elevation_overlay(intent) or len(routes) != 1:
        return None
    route_id = _single_route_id(points)
    route_points = tuple(
        point
        for point in points
        if point.workout_id == route_id and point.latitude is not None and point.longitude is not None and point.elevation_m is not None
    )
    if len(route_points) < 3:
        return None
    distances = _route_distances_km(route_points)
    raw_elevations = tuple(float(point.elevation_m) for point in route_points)
    elevations = _smoothed_elevations(distances, raw_elevations)
    grades = _smoothed_grades(distances, elevations)
    samples = tuple(
        RouteElevationSample(distance_km=distance, elevation_m=elevation, grade=grade)
        for distance, elevation, grade in zip(distances, elevations, grades, strict=True)
    )
    min_index = min(range(len(samples)), key=lambda index: samples[index].elevation_m)
    max_index = max(range(len(samples)), key=lambda index: samples[index].elevation_m)
    if abs(samples[max_index].elevation_m - samples[min_index].elevation_m) < 1.0:
        return None
    return RouteElevationProfile(
        samples=samples,
        min_index=min_index,
        max_index=max_index,
        min_grade=min(grades),
        max_grade=max(grades),
    )


def _single_route_id(points: tuple[WorkoutPointRecord, ...]) -> str:
    for point in points:
        if point.latitude is not None and point.longitude is not None:
            return point.workout_id
    return ""


def _route_distances_km(points: tuple[WorkoutPointRecord, ...]) -> tuple[float, ...]:
    recorded = tuple(point.distance_km for point in points)
    if _valid_distance_series(recorded):
        return tuple(float(distance) for distance in recorded if distance is not None)
    distances = [0.0]
    for current, following in zip(points, points[1:], strict=False):
        if current.latitude is None or current.longitude is None or following.latitude is None or following.longitude is None:
            distances.append(distances[-1])
            continue
        distances.append(distances[-1] + _distance_m(current.latitude, current.longitude, following.latitude, following.longitude) / 1000)
    return tuple(distances)


def _valid_distance_series(values: tuple[float | None, ...]) -> bool:
    if any(value is None for value in values):
        return False
    numeric = tuple(float(value) for value in values if value is not None)
    return len(numeric) >= 2 and numeric[-1] > numeric[0] and all(right >= left for left, right in zip(numeric, numeric[1:], strict=False))


def _smoothed_grades(distances_km: tuple[float, ...], elevations_m: tuple[float, ...]) -> tuple[float, ...]:
    raw: list[float] = []
    for index, (current_distance, next_distance) in enumerate(zip(distances_km, distances_km[1:], strict=False)):
        delta_m = (next_distance - current_distance) * 1000
        if delta_m <= 0:
            raw.append(0.0)
            continue
        raw.append((elevations_m[index + 1] - elevations_m[index]) / delta_m)
    raw.append(raw[-1] if raw else 0.0)
    smoothed: list[float] = []
    for index in range(len(raw)):
        window = raw[max(0, index - 2) : min(len(raw), index + 3)]
        smoothed.append(sum(window) / len(window))
    return tuple(smoothed)


def _smoothed_elevations(distances_km: tuple[float, ...], elevations_m: tuple[float, ...]) -> tuple[float, ...]:
    if len(elevations_m) < 5:
        return elevations_m
    route_distance_m = max(0.0, (distances_km[-1] - distances_km[0]) * 1000)
    radius_m = max(30.0, min(100.0, route_distance_m * 0.02))
    median_values: list[float] = []
    distances_m = tuple(distance * 1000 for distance in distances_km)
    for center_index, center_distance in enumerate(distances_m):
        window = [
            elevation
            for distance, elevation in zip(distances_m, elevations_m, strict=True)
            if abs(distance - center_distance) <= radius_m
        ]
        if not window:
            median_values.append(elevations_m[center_index])
            continue
        ordered = sorted(window)
        median_values.append(ordered[len(ordered) // 2])
    smoothed: list[float] = []
    for index in range(len(median_values)):
        window = median_values[max(0, index - 2) : min(len(median_values), index + 3)]
        smoothed.append(sum(window) / len(window))
    return tuple(smoothed)


def _elevation_overlay_status(
    profile: RouteElevationProfile | None,
    routes: tuple[RoutePolyline, ...],
    intent: VisualizationIntent,
) -> str:
    if not _show_elevation_overlay(intent):
        return "hidden_by_modifier"
    if len(routes) != 1:
        return "multi_route_hidden"
    return "rendered" if profile is not None else "missing_data"


def _elevation_min(profile: RouteElevationProfile | None) -> float | None:
    if profile is None:
        return None
    return round(profile.samples[profile.min_index].elevation_m)


def _elevation_max(profile: RouteElevationProfile | None) -> float | None:
    if profile is None:
        return None
    return round(profile.samples[profile.max_index].elevation_m)


def _route_waypoints_from_metadata(workout: WorkoutRecord) -> tuple[RouteWaypoint, ...]:
    raw_waypoints = workout.metadata.get("waypoints", ())
    if not isinstance(raw_waypoints, list | tuple):
        return ()
    waypoints: list[RouteWaypoint] = []
    for raw in raw_waypoints:
        if not isinstance(raw, dict):
            continue
        latitude = _optional_numeric(raw.get("latitude"))
        longitude = _optional_numeric(raw.get("longitude"))
        if latitude is None or longitude is None:
            continue
        label = _waypoint_label(raw)
        waypoint_type = str(raw.get("type") or raw.get("waypoint_type") or raw.get("symbol") or "").strip()
        waypoints.append(RouteWaypoint(latitude=latitude, longitude=longitude, label=label, waypoint_type=waypoint_type))
    return tuple(waypoints)


def _waypoint_label(raw: dict[str, object]) -> str:
    name = str(raw.get("name") or raw.get("label") or "").strip()
    comment = str(raw.get("comment") or raw.get("cmt") or "").strip()
    description = str(raw.get("description") or raw.get("desc") or "").strip()
    if comment:
        return comment
    if description:
        return description
    return name


def _waypoint_status(
    waypoint_count: int,
    rendered: tuple[RouteWaypoint, ...],
    routes: tuple[RoutePolyline, ...],
    intent: VisualizationIntent,
) -> str:
    if waypoint_count <= 0:
        return "none"
    if not _show_waypoints(intent):
        return "hidden_by_modifier"
    if len(routes) != 1:
        return "multi_route_hidden"
    return "rendered" if rendered else "missing_coordinates"


def _waypoint_distances_from_start(
    waypoints: tuple[RouteWaypoint, ...],
    route: RoutePolyline,
) -> tuple[float | None, ...]:
    route_points = route.points
    if len(route_points) < 2:
        return tuple(None for _ in waypoints)
    xy_points = tuple(_local_xy_m(point.latitude, point.longitude, route_points[0].latitude) for point in route_points)
    cumulative = [0.0]
    for current, following in zip(route_points, route_points[1:], strict=False):
        cumulative.append(cumulative[-1] + _distance_m(current.latitude, current.longitude, following.latitude, following.longitude))
    distances: list[float | None] = []
    for waypoint in waypoints:
        waypoint_xy = _local_xy_m(waypoint.latitude, waypoint.longitude, route_points[0].latitude)
        best_distance_m: float | None = None
        best_error: float | None = None
        for index, (start_xy, end_xy) in enumerate(zip(xy_points, xy_points[1:], strict=False)):
            projected_ratio, error = _project_point_to_segment(waypoint_xy, start_xy, end_xy)
            segment_length = cumulative[index + 1] - cumulative[index]
            candidate_distance = cumulative[index] + projected_ratio * segment_length
            if best_error is None or error < best_error:
                best_error = error
                best_distance_m = candidate_distance
        distances.append(round(best_distance_m / 1000, 1) if best_distance_m is not None else None)
    return tuple(distances)


def _project_point_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 0:
        return 0.0, math.hypot(point[0] - start[0], point[1] - start[1])
    ratio = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    projected = (start[0] + ratio * dx, start[1] + ratio * dy)
    return ratio, math.hypot(point[0] - projected[0], point[1] - projected[1])


def _local_xy_m(latitude: float, longitude: float, reference_latitude: float) -> tuple[float, float]:
    meters_per_degree_lat = 111_320.0
    meters_per_degree_lon = meters_per_degree_lat * math.cos(math.radians(reference_latitude))
    return longitude * meters_per_degree_lon, latitude * meters_per_degree_lat


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(a))


def _is_route_color_metric_supported(metric: str) -> bool:
    return metric in {"heart_rate_bpm", "elevation_m", "grade", "pace_s_per_km"}


def _route_color_mode(metric: str) -> str:
    if metric == "grade":
        return ROUTE_COLOR_MODE_ELEVATION_GRADE
    return ROUTE_COLOR_MODE_METRIC


def _route_color_status(routes: tuple[RoutePolyline, ...], *, route_color_metric: str) -> str:
    if not route_color_metric:
        return "none"
    values = tuple(point.color_value for route in routes for point in route.points if point.color_value is not None)
    if len(values) < 2:
        return "missing_data"
    return "ok"


def _route_color_domain(routes: tuple[RoutePolyline, ...], metric: str) -> tuple[float, float] | None:
    if any(route.color_mode == ROUTE_COLOR_MODE_ELEVATION_GRADE for route in routes):
        values = tuple(point.color_value for route in routes for point in route.points if point.color_value is not None and math.isfinite(point.color_value))
        if not values:
            return None
        return min(values), max(values)
    values = tuple(point.color_value for route in routes for point in route.points if point.color_value is not None)
    return visual_domain(metric, values)


def _route_metric_values(
    points: list[WorkoutPointRecord],
    metric: str,
    *,
    route_color_mode: str = ROUTE_COLOR_MODE_METRIC,
) -> tuple[float | None, ...]:
    if not metric:
        return tuple(None for _ in points)
    if route_color_mode == ROUTE_COLOR_MODE_ELEVATION_GRADE:
        return _route_elevation_grade_values(points)
    return clean_metric_series(metric, tuple(_route_point_metric_value(point, metric) for point in points))


def _route_elevation_grade_values(points: list[WorkoutPointRecord]) -> tuple[float | None, ...]:
    if len(points) < 2 or any(point.elevation_m is None for point in points):
        return tuple(None for _ in points)
    route_points = tuple(points)
    distances = _route_distances_km(route_points)
    if len(distances) != len(route_points):
        return tuple(None for _ in points)
    elevations = _smoothed_elevations(distances, tuple(float(point.elevation_m) for point in route_points if point.elevation_m is not None))
    return _smoothed_grades(distances, elevations)


def _route_point_metric_value(point: WorkoutPointRecord, metric: str) -> float | None:
    if metric == "heart_rate_bpm":
        return point.heart_rate_bpm
    if metric == "elevation_m":
        return point.elevation_m
    if metric == "grade":
        return None
    if metric == "pace_s_per_km":
        return point.pace_s_per_km
    return None


def _route_labels_from_manifest(manifest: DatasetManifest) -> dict[str, str]:
    dataset = manifest.dataset("workout_period")
    if dataset is None:
        return {}
    labels: dict[str, str] = {}
    for row in dataset.rows:
        workout_id = str(row.get("workout_id") or "")
        if not workout_id:
            continue
        labels[workout_id] = _route_label_from_values(
            start_time_local=str(row.get("workout_start_local") or ""),
            local_date=str(row.get("workout_date") or ""),
            distance_km=_optional_numeric(row.get("workout_distance_km") if row.get("workout_distance_km") is not None else row.get("distance_km")),
            fallback=workout_id,
        )
    return labels


def _route_points_from_manifest(manifest: DatasetManifest) -> tuple[WorkoutPointRecord, ...]:
    dataset = manifest.dataset("route_points")
    if dataset is None:
        return ()
    points = []
    for index, row in enumerate(dataset.rows):
        points.append(
            WorkoutPointRecord(
                workout_id=str(row.get("workout_id", "")),
                point_index=int(row.get("point_index", index) or index),
                elapsed_s=_optional_numeric(row.get("elapsed_s")),
                distance_km=_optional_numeric(row.get("distance_km")),
                latitude=_optional_numeric(row.get("latitude")),
                longitude=_optional_numeric(row.get("longitude")),
                elevation_m=_optional_numeric(row.get("elevation_m")),
                heart_rate_bpm=_optional_numeric(row.get("heart_rate_bpm")),
                segment_index=int(row["segment_index"]) if isinstance(row.get("segment_index"), int) else None,
            )
        )
    return tuple(points)


def _render_spec(
    workout: WorkoutRecord,
    spec: VisualizationSpec,
    dataset: Dataset,
    *,
    layout_mode: str = "single_axis",
    render_size: tuple[int, int] = (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT),
    language: SupportedLanguage = SupportedLanguage.FI,
) -> RenderedSpec:
    rows = _transformed_rows(spec, dataset)
    chart_title = _chart_title(workout, spec, dataset, language=language)
    chart_subtitle = _chart_subtitle(workout, language=language)
    legend_title = _legend_title(language)
    x_label = _metric_label(spec.x.column_id, language=language)
    y_label = _y_axis_label(spec, language=language)
    if _should_render_metric_aggregate_bars(spec, dataset):
        renderer = resolve_renderer("bar")
        return RenderedSpec(
            content=renderer.render_bar_chart_png(
                BarChart(
                    title=chart_title,
                    subtitle=chart_subtitle,
                    legend_title=legend_title,
                    width=render_size[0],
                    height=render_size[1],
                    x_label=_metric_axis_label(language),
                    y_label=y_label,
                    y_tick_format=_y_tick_format(spec.y[0].column_id) if len(spec.y) == 1 else "number",
                    bars=_aggregate_bars(spec, rows),
                )
            ),
            chart_type="bar",
            renderer=renderer.name,
        )
    if spec.mark == "pie":
        renderer = resolve_renderer("pie")
        return RenderedSpec(
            content=renderer.render_pie_chart_png(
                PieChart(
                    title=chart_title,
                    subtitle=chart_subtitle,
                    legend_title=legend_title,
                    width=render_size[0],
                    height=render_size[1],
                    value_label=y_label,
                    value_format=_bar_tick_format(spec),
                    slices=tuple(
                        PieSlice(
                            label=str(row.get(spec.x.column_id, "")),
                            value=_numeric(row.get(spec.y[0].column_id)),
                            color=_color_hint(row.get("color_hint")),
                        )
                        for row in rows
                    ),
                )
            ),
            chart_type="pie",
            renderer=renderer.name,
        )
    if spec.mark == "bar":
        renderer = resolve_renderer("bar")
        return RenderedSpec(
            content=renderer.render_bar_chart_png(
                BarChart(
                    title=chart_title,
                    subtitle=chart_subtitle,
                    legend_title=legend_title,
                    width=render_size[0],
                    height=render_size[1],
                    x_label=x_label,
                    y_label=y_label,
                    y_tick_format=_bar_tick_format(spec),
                    bars=tuple(
                        Bar(
                            label=str(row.get(spec.x.column_id, "")),
                            value=_numeric(row.get(spec.y[0].column_id)),
                            color=_color_hint(row.get("color_hint")),
                        )
                        for row in rows
                    ),
                )
            ),
            chart_type="bar",
            renderer=renderer.name,
        )
    series = tuple(
        RenderSeries(
            metric=encoding.column_id,
            values=tuple(_optional_numeric(row.get(encoding.column_id)) for row in rows),
            label=_series_label(encoding.column_id, language=language),
        )
        for encoding in spec.y
    )
    if "smooth" in spec.transforms or "rolling_average" in spec.transforms:
        series = _apply_rolling_average(series)
    if _should_normalize_to_primary_range(spec, layout_mode):
        series = _apply_normalization(series)
    if layout_mode == "small_multiples" and len(series) > 1:
        renderer = resolve_renderer("multi_panel_line")
        return RenderedSpec(
            content=renderer.render_multi_panel_line_chart_png(
                MultiPanelLineChart(
                    title=chart_title,
                    subtitle=chart_subtitle,
                    legend_title=legend_title,
                    width=render_size[0],
                    height=render_size[1],
                    x_label=x_label,
                    x_tick_format=_tick_format(spec.x.column_id),
                    x_values=tuple(_optional_numeric(row.get(spec.x.column_id)) for row in rows),
                    panels=tuple(
                        LinePanel(
                            series=current,
                            y_label=_metric_label(current.metric, language=language),
                            y_tick_format=_y_tick_format(current.metric),
                            invert_y=_invert_y_axis(current.metric),
                        )
                        for current in series
                    ),
                )
            ),
            chart_type="multi_panel_line",
            renderer=renderer.name,
        )
    renderer = resolve_renderer("line")
    return RenderedSpec(
        content=renderer.render_line_chart_png(
            LineChart(
                title=chart_title,
                subtitle=chart_subtitle,
                legend_title=legend_title,
                width=render_size[0],
                height=render_size[1],
                x_label=x_label,
                y_label=y_label,
                x_tick_format=_tick_format(spec.x.column_id),
                y_tick_format=_y_tick_format(spec.y[0].column_id) if len(spec.y) == 1 else "number",
                invert_y=_invert_y_axis(spec.y[0].column_id) if len(spec.y) == 1 else False,
                x_values=tuple(_optional_numeric(row.get(spec.x.column_id)) for row in rows),
                series=series,
            )
        ),
        chart_type="line",
        renderer=renderer.name,
    )


def _transformed_rows(spec: VisualizationSpec, dataset: Dataset) -> tuple[dict[str, Any], ...]:
    rows = dataset.rows
    if "filter_non_null" in spec.transforms:
        required_columns = (spec.x.column_id,) + tuple(encoding.column_id for encoding in spec.y)
        rows = tuple(row for row in rows if all(row.get(column_id) is not None for column_id in required_columns))
    if "as_percentage_of_total" in spec.transforms:
        rows = _as_percentage_of_total_rows(spec, rows)
    return rows


def _as_percentage_of_total_rows(spec: VisualizationSpec, rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    if len(spec.y) != 1:
        return rows
    column_id = spec.y[0].column_id
    total = sum(_numeric(row.get(column_id)) for row in rows)
    if total <= 0:
        return tuple({**row, column_id: 0.0} for row in rows)
    return tuple({**row, column_id: (_numeric(row.get(column_id)) / total) * 100.0} for row in rows)


def _aggregate_bars(spec: VisualizationSpec, rows: tuple[dict[str, Any], ...]) -> tuple[Bar, ...]:
    aggregation = "sum" if "aggregate_sum" in spec.transforms else "avg"
    return tuple(
        Bar(
            label=encoding.column_id,
            value=_aggregate_values(
                tuple(_optional_numeric(row.get(encoding.column_id)) for row in rows),
                aggregation=aggregation,
            ),
        )
        for encoding in spec.y
    )


def _should_render_metric_aggregate_bars(spec: VisualizationSpec, dataset: Dataset) -> bool:
    if "aggregate_sum" not in spec.transforms and "aggregate_avg" not in spec.transforms:
        return False
    x_column = next((column for column in dataset.columns if column.column_id == spec.x.column_id), None)
    if spec.mark in {"bar", "pie"} and x_column is not None and x_column.semantic_type in {"nominal", "ordinal"}:
        return False
    return True


def _aggregate_values(values: tuple[float | None, ...], *, aggregation: str) -> float:
    numeric = tuple(value for value in values if value is not None)
    if not numeric:
        return 0.0
    if aggregation == "sum":
        return sum(numeric)
    return sum(numeric) / len(numeric)


def _scaled_metrics(spec: VisualizationSpec, layout_mode: str) -> tuple[str, ...]:
    if not _should_normalize_to_primary_range(spec, layout_mode):
        return ()
    return tuple(encoding.column_id for encoding in spec.y[1:])


def _effective_layout_mode(requested_layout: str, spec: VisualizationSpec) -> str:
    requested = requested_layout.strip().lower()
    if requested in {"single_axis", "small_multiples"}:
        return requested
    if spec.mark != "line" or len(spec.y) <= 1:
        return "single_axis"
    units = {_metric_unit(encoding.column_id) for encoding in spec.y}
    return "single_axis" if len(units) <= 1 else "small_multiples"


def _should_normalize_to_primary_range(spec: VisualizationSpec, layout_mode: str) -> bool:
    if len(spec.y) <= 1 or layout_mode != "single_axis":
        return False
    return "normalize_to_primary_range" in spec.transforms or not _metrics_share_unit(spec)


def _metrics_share_unit(spec: VisualizationSpec) -> bool:
    return len({_metric_unit(encoding.column_id) for encoding in spec.y}) <= 1


def _chart_title(
    workout: WorkoutRecord | str,
    spec: VisualizationSpec,
    dataset: Dataset | None = None,
    *,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> str:
    if isinstance(workout, str):
        return workout
    if not _is_period_workout(workout):
        return workout.title
    return _chart_subject(spec, dataset, language=language)


def _chart_subject(spec: VisualizationSpec, dataset: Dataset | None = None, *, language: SupportedLanguage) -> str:
    if len(spec.y) > 1:
        return "Mittarit" if language == SupportedLanguage.FI else "Metrics"
    if dataset is not None and "as_percentage_of_total" in spec.transforms:
        x_column = _column_semantic_type(dataset, spec.x.column_id)
        if x_column in {"nominal", "ordinal"}:
            return _metric_subject(spec.x.column_id, language=language)
    if spec.y:
        return _metric_subject(spec.y[0].column_id, language=language)
    return "Kaavio" if language == SupportedLanguage.FI else "Chart"


def _column_semantic_type(dataset: Dataset, column_id: str) -> str:
    column = next((candidate for candidate in dataset.columns if candidate.column_id == column_id), None)
    return column.semantic_type if column is not None else ""


def _chart_subtitle(workout: WorkoutRecord, *, language: SupportedLanguage = SupportedLanguage.FI) -> str:
    date_text = _format_period_range(workout.local_date) if _is_period_workout(workout) else _format_route_datetime(workout.start_time_local or workout.start_time_utc or workout.local_date)
    parts = (
        date_text,
        _format_number(workout.distance_km, suffix=" km", digits=1),
        _format_route_duration(workout.duration_s),
        _format_route_average_hr(workout.avg_hr_bpm, language=language),
    )
    return " - ".join(part for part in parts if part)


def _is_period_workout(workout: WorkoutRecord) -> bool:
    return (workout.primary_kind or workout.kind).strip().lower() == "period" or ".." in (workout.local_date or "")


def _format_period_range(value: str | None) -> str:
    if not value:
        return ""
    start, separator, end = value.partition("..")
    if not separator:
        return _format_route_datetime(value)
    start_text = _format_route_datetime(start)
    end_text = _format_route_datetime(end)
    return " - ".join(part for part in (start_text, end_text) if part)


def _route_chart_subtitle(workout: WorkoutRecord, *, language: SupportedLanguage, estimate_summary: str = "") -> str:
    parts = (
        _format_route_datetime(workout.start_time_local or workout.start_time_utc or workout.local_date),
        _format_route_distance_and_ascent(workout, language=language),
        estimate_summary,
        _format_route_duration(workout.duration_s),
        _format_route_average_hr(workout.avg_hr_bpm, language=language),
    )
    return " - ".join(part for part in parts if part)


def _route_map_title(title: str, *, language: SupportedLanguage) -> str:
    prefix = "Reitti" if language == SupportedLanguage.FI else "Route"
    clean = title.strip()
    if clean.lower().startswith(f"{prefix.lower()}:"):
        return clean
    return f"{prefix}: {clean}" if clean else prefix


def _format_route_distance_and_ascent(workout: WorkoutRecord, *, language: SupportedLanguage) -> str:
    distance = _format_number(workout.distance_km, suffix=" km", digits=1)
    if not distance:
        return ""
    if workout.ascent_m is None:
        return distance
    if language == SupportedLanguage.FI:
        return f"{distance} - {round(workout.ascent_m)} nm"
    return f"{distance} - ascent {round(workout.ascent_m)} m"


def _route_legend_title(routes: tuple[RoutePolyline, ...], *, language: SupportedLanguage) -> str:
    if len(routes) > 1:
        return "Treenit" if language == SupportedLanguage.FI else "Workouts"
    return "Reitti" if language == SupportedLanguage.FI else "Route"


def _route_color_metric_label(metric: str, *, language: SupportedLanguage) -> str:
    if language == SupportedLanguage.FI:
        labels = {
            "heart_rate_bpm": "Syke",
            "elevation_m": "Korkeus",
            "grade": "Jyrkkyys",
            "pace_s_per_km": "Vauhti (min/km)",
        }
        return labels.get(metric, _series_label(metric, language=language))
    labels = {
        "grade": "Grade",
        "pace_s_per_km": "Pace (min/km)",
    }
    return labels.get(metric, _series_label(metric, language=language))


SOCIAL_STAT_METRICS = frozenset(
    {"distance_km", "duration_s", "avg_hr_bpm", "heart_rate_bpm", "max_hr_bpm", "ascent_m", "pace_s_per_km", "local_date"}
)
SOCIAL_DEFAULT_STATS = ("distance_km", "duration_s", "avg_hr_bpm")


def _social_metric_selection(intent: VisualizationIntent) -> tuple[str, ...]:
    requested = tuple(metric for metric in intent.y_metrics if metric in SOCIAL_STAT_METRICS)
    if requested:
        return tuple(_canonical_social_stat_metric(metric) for metric in requested)
    return SOCIAL_DEFAULT_STATS


def _canonical_social_stat_metric(metric: str) -> str:
    if metric == "heart_rate_bpm":
        return "avg_hr_bpm"
    return metric


def _social_stats(
    workout: WorkoutRecord,
    intent: VisualizationIntent,
    *,
    language: SupportedLanguage,
) -> tuple[SocialImageStat, ...]:
    stats = []
    for metric in dict.fromkeys(_social_metric_selection(intent)):
        value = _social_stat_value(workout, metric, language=language)
        if value:
            stats.append(SocialImageStat(label=_social_stat_label(metric, language=language), value=value))
    return tuple(stats)


def _social_stat_label(metric: str, *, language: SupportedLanguage) -> str:
    return _series_label(metric, language=language)


def _social_stat_value(workout: WorkoutRecord, metric: str, *, language: SupportedLanguage) -> str:
    del language
    if metric == "distance_km":
        return _format_number(workout.distance_km, suffix=" km", digits=1)
    if metric == "duration_s":
        return _format_route_duration(workout.duration_s)
    if metric == "avg_hr_bpm":
        return _format_number(workout.avg_hr_bpm, suffix=" bpm", digits=0)
    if metric == "ascent_m":
        return _format_number(workout.ascent_m, suffix=" m", digits=0)
    if metric == "pace_s_per_km":
        return _format_duration(workout.pace_s_per_km) + "/km" if workout.pace_s_per_km is not None else ""
    if metric == "max_hr_bpm":
        return _format_number(workout.max_hr_bpm, suffix=" bpm", digits=0)
    if metric == "local_date":
        return _format_route_datetime(workout.start_time_local or workout.start_time_utc or workout.local_date)
    return ""


def _route_label(workout: WorkoutRecord | None, fallback: str) -> str:
    if workout is None:
        return fallback
    return _route_label_from_values(
        start_time_local=workout.start_time_local or workout.start_time_utc or "",
        local_date=workout.local_date,
        distance_km=workout.distance_km,
        fallback=fallback,
    )


def _route_label_from_values(
    *,
    start_time_local: str | None,
    local_date: str | None,
    distance_km: float | None,
    fallback: str,
) -> str:
    parts = (
        _format_route_datetime(start_time_local or local_date),
        _format_number(distance_km, suffix=" km", digits=1),
    )
    label = " ".join(part for part in parts if part)
    return label or fallback


def _y_axis_label(spec: VisualizationSpec, *, language: SupportedLanguage = SupportedLanguage.FI) -> str:
    if "as_percentage_of_total" in spec.transforms:
        return "Osuus (%)" if language == SupportedLanguage.FI else "Share (%)"
    if len(spec.y) == 1:
        return _metric_label(spec.y[0].column_id, language=language)
    return "Arvo" if language == SupportedLanguage.FI else "Value"


def _bar_tick_format(spec: VisualizationSpec) -> str:
    if "as_percentage_of_total" in spec.transforms:
        return "percentage"
    return _y_tick_format(spec.y[0].column_id)


def _metric_label(metric: str, *, language: SupportedLanguage = SupportedLanguage.FI) -> str:
    if language == SupportedLanguage.FI:
        labels = {
            "elapsed_s": "Aika",
            "distance_m": "Matka (m)",
            "distance_km": "Matka (km)",
            "latitude": "Leveysaste",
            "longitude": "Pituusaste",
            "elevation_m": "Korkeus (m)",
            "heart_rate_bpm": "Syke",
            "cadence_spm": "Kadenssi",
            "pace_s_per_km": "Vauhti (min/km)",
            "heart_rate_zone_seconds": "Aika alueella",
            "zone_label": "Sykealue",
            "zone_key": "Sykealue",
            "duration_s": "Kesto",
            "ascent_m": "Nousu (m)",
            "avg_hr_bpm": "Keskisyke",
            "max_hr_bpm": "Maksimisyke",
            "point_count": "Pisteet",
            "local_date": "Päivä",
        }
        return labels.get(metric, metric.replace("_", " ").title())
    labels = {
        "elapsed_s": "Time",
        "distance_m": "Distance (m)",
        "distance_km": "Distance (km)",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "elevation_m": "Elevation (m)",
        "heart_rate_bpm": "Heart rate",
        "cadence_spm": "Cadence",
        "pace_s_per_km": "Pace (min/km)",
        "heart_rate_zone_seconds": "Time in zone",
        "zone_label": "Heart-rate zone",
        "zone_key": "Heart-rate zone",
        "duration_s": "Duration",
        "ascent_m": "Ascent (m)",
        "avg_hr_bpm": "Average HR",
        "max_hr_bpm": "Max HR",
        "point_count": "Point count",
        "local_date": "Date",
    }
    return labels.get(metric, metric.replace("_", " ").title())


def _metric_subject(metric: str, *, language: SupportedLanguage) -> str:
    if language == SupportedLanguage.FI:
        labels = {
            "elapsed_s": "Aika",
            "distance_m": "Matka",
            "distance_km": "Matka",
            "elevation_m": "Korkeus",
            "heart_rate_bpm": "Syke",
            "cadence_spm": "Kadenssi",
            "pace_s_per_km": "Vauhti",
            "heart_rate_zone_seconds": "Sykealueet",
            "zone_label": "Sykealueet",
            "zone_key": "Sykealueet",
            "duration_s": "Kesto",
            "ascent_m": "Nousu",
            "avg_hr_bpm": "Keskisyke",
            "max_hr_bpm": "Maksimisyke",
        }
        return labels.get(metric, _series_label(metric, language=language))
    labels = {
        "elapsed_s": "Time",
        "distance_m": "Distance",
        "distance_km": "Distance",
        "elevation_m": "Elevation",
        "heart_rate_bpm": "Heart rate",
        "cadence_spm": "Cadence",
        "pace_s_per_km": "Pace",
        "heart_rate_zone_seconds": "Heart-rate zones",
        "zone_label": "Heart-rate zones",
        "zone_key": "Heart-rate zones",
        "duration_s": "Duration",
        "ascent_m": "Ascent",
        "avg_hr_bpm": "Average HR",
        "max_hr_bpm": "Max HR",
    }
    return labels.get(metric, _series_label(metric, language=language))


def _legend_title(language: SupportedLanguage) -> str:
    return "Selite" if language == SupportedLanguage.FI else "Legend"


def _metric_axis_label(language: SupportedLanguage) -> str:
    return "Mittari" if language == SupportedLanguage.FI else "Metric"


def _color_hint(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    named = {
        "blue": (37, 99, 235),
        "green": (22, 163, 74),
        "yellow": (234, 179, 8),
        "orange": (249, 115, 22),
        "red": (220, 38, 38),
        "purple": (124, 58, 237),
        "cyan": (8, 145, 178),
        "pink": (190, 24, 93),
    }
    if normalized in named:
        return named[normalized]
    if len(normalized) == 7 and normalized.startswith("#"):
        try:
            return (
                int(normalized[1:3], 16),
                int(normalized[3:5], 16),
                int(normalized[5:7], 16),
            )
        except ValueError:
            return None
    return None


def _metric_unit(metric: str) -> str:
    return metric_unit(metric)


def _series_label(metric: str, *, language: SupportedLanguage = SupportedLanguage.FI) -> str:
    return _metric_label(metric, language=language).split(" (", 1)[0]


def _tick_format(metric: str) -> str:
    return metric_tick_format(metric)


def _y_tick_format(metric: str) -> str:
    return metric_tick_format(metric)


def _invert_y_axis(metric: str) -> bool:
    return metric_invert_axis(metric)


def _format_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    total_seconds = int(round(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_route_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    total_seconds = max(0, int(round(value)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}min")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def _format_route_datetime(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    has_time = "T" in text or " " in text
    if has_time:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(_route_display_timezone())
            return f"{parsed.day}/{parsed.month}/{parsed.year} {parsed.hour}:{parsed.minute}"
    date_part, _, time_part = text.partition("T")
    if not time_part and " " in text:
        date_part, _, time_part = text.partition(" ")
    pieces = date_part.split("-")
    if len(pieces) != 3 or not all(piece.isdecimal() for piece in pieces):
        return text
    year, month, day = (int(piece) for piece in pieces)
    if time_part:
        raw_hour, _, rest = time_part.partition(":")
        raw_minute = rest.split(":", 1)[0]
        if raw_hour.isdecimal() and raw_minute.isdecimal():
            return f"{day}/{month}/{year} {int(raw_hour)}:{int(raw_minute)}"
    return f"{day}/{month}/{year}"


def _route_display_timezone() -> ZoneInfo:
    try:
        return ZoneInfo("Europe/Helsinki")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _format_route_average_hr(value: object, *, language: SupportedLanguage) -> str:
    if not isinstance(value, (int, float)):
        return ""
    label = "Keskisyke" if language == SupportedLanguage.FI else "Avg HR"
    return f"{label} {int(round(value))}"


def _format_date(value: str | None) -> str:
    return value or ""


def _format_kind(value: str) -> str:
    labels = {
        "run": "Run",
        "running": "Run",
        "ride": "Ride",
        "cycling": "Ride",
        "walk": "Walk",
        "activity": "Activity",
        "route": "Route",
    }
    return labels.get(value.strip().lower(), value)


def _format_number(value: object, *, prefix: str = "", suffix: str = "", digits: int) -> str:
    if not isinstance(value, (int, float)):
        return ""
    if digits <= 0:
        formatted = str(int(round(value)))
    else:
        formatted = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return f"{prefix}{formatted}{suffix}"


def _is_comparison_intent(intent: VisualizationIntent) -> bool:
    comparison = intent.comparison_mode.strip().lower()
    return comparison in {"recent", "compare", "comparison", "previous", "previous_period", "multi", "multiple"}


def _numeric(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _optional_numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _apply_normalization(series: tuple[RenderSeries, ...]) -> tuple[RenderSeries, ...]:
    if len(series) <= 1:
        return series
    primary = series[0]
    target = _domain(primary.values)
    normalized = [primary]
    for current in series[1:]:
        source = _robust_domain(current.values)
        normalized.append(
            RenderSeries(
                metric=current.metric,
                values=tuple(_normalize(value, source.domain, target, clip=True) for value in current.values),
                scaled=True,
                clipped=source.clipped,
                smoothed=current.smoothed,
                label=current.label,
            )
        )
    return tuple(normalized)


def _apply_rolling_average(series: tuple[RenderSeries, ...], *, window_size: int | None = None) -> tuple[RenderSeries, ...]:
    return tuple(
        RenderSeries(
            metric=current.metric,
            values=_rolling_average(current.values, window_size=window_size or _explicit_smooth_window(current.values)),
            scaled=current.scaled,
            clipped=current.clipped,
            smoothed=True,
            label=current.label,
        )
        for current in series
    )


def _explicit_smooth_window(values: tuple[float | None, ...]) -> int:
    visible_points = sum(1 for value in values if value is not None)
    window = max(5, min(61, (visible_points // 80) * 2 + 1))
    return window if window % 2 == 1 else window + 1


def _rolling_average(values: tuple[float | None, ...], *, window_size: int) -> tuple[float | None, ...]:
    if window_size <= 1:
        return values
    radius = window_size // 2
    smoothed: list[float | None] = []
    for index, value in enumerate(values):
        if value is None:
            smoothed.append(None)
            continue
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        window = [candidate for candidate in values[start:end] if candidate is not None]
        smoothed.append(sum(window) / len(window) if window else None)
    return tuple(smoothed)


def _domain(values: tuple[float | None, ...]) -> tuple[float, float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return (0.0, 1.0)
    low = min(numeric)
    high = max(numeric)
    if low == high:
        return (low, high + 1.0)
    return (low, high)


@dataclass(frozen=True)
class RobustDomain:
    domain: tuple[float, float]
    clipped: bool = False


def _robust_domain(values: tuple[float | None, ...]) -> RobustDomain:
    numeric = sorted(value for value in values if value is not None)
    if len(numeric) < 8:
        return RobustDomain(_domain(values))
    low = _percentile(numeric, 0.05)
    high = _percentile(numeric, 0.95)
    if low == high:
        return RobustDomain(_domain(values))
    full_low = numeric[0]
    full_high = numeric[-1]
    full_range = full_high - full_low
    robust_range = high - low
    if full_range <= robust_range * 1.5:
        return RobustDomain((full_low, full_high))
    return RobustDomain((low, high), clipped=True)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    ratio = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * ratio


def _normalize(
    value: float | None,
    source: tuple[float, float],
    target: tuple[float, float],
    *,
    clip: bool = False,
) -> float | None:
    if value is None:
        return None
    source_low, source_high = source
    target_low, target_high = target
    if clip:
        value = min(max(value, source_low), source_high)
    return target_low + ((value - source_low) / (source_high - source_low)) * (target_high - target_low)
