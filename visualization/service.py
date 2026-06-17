from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.config import MapsConfig, RenderersConfig
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
    RoutePoint,
    RoutePolyline,
    RenderSeries,
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
    renderers_config: RenderersConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
) -> VisualizationArtifact:
    if _is_route_map_intent(intent):
        return _render_route_map_visualization(
            workout,
            points,
            intent,
            filename_prefix=workout.workout_id,
            tile_cache_root=tile_cache_root,
            maps_config=maps_config,
            renderers_config=renderers_config,
            language=language,
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
    rendered = _render_spec(workout, spec, dataset, layout_mode=layout_mode, renderers_config=renderers_config, render_size=render_size, language=language)
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
    renderers_config: RenderersConfig | None = None,
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
            renderers_config=renderers_config,
            language=language,
            route_labels=route_labels,
        )
    request = _dataset_request(intent, comparison=False)
    return _render_from_manifest(title_workout, intent, request, manifest, filename_prefix=title_workout.workout_id, renderers_config=renderers_config, language=language)


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
    renderers_config: RenderersConfig | None = None,
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
    rendered = _render_spec(workout, spec, dataset, layout_mode=layout_mode, renderers_config=renderers_config, render_size=render_size, language=language)
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


def _render_size(intent: VisualizationIntent) -> tuple[int, int]:
    if intent.render_width > 0 and intent.render_height > 0:
        return intent.render_width, intent.render_height
    return DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT


def _render_route_map_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    filename_prefix: str,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
    renderers_config: RenderersConfig | None = None,
    language: SupportedLanguage = SupportedLanguage.FI,
    route_labels: dict[str, str] | None = None,
) -> VisualizationArtifact:
    workouts_by_id = {workout.workout_id: workout}
    route_color_metric = intent.route_color_metric if _is_route_color_metric_supported(intent.route_color_metric) else ""
    routes = _route_polylines(points, workouts_by_id=workouts_by_id, route_labels=route_labels, route_color_metric=route_color_metric)
    if not routes:
        raise MissingPrimaryMetricError("route")
    render_size = _render_size(intent)
    color_status = _route_color_status(routes, route_color_metric=route_color_metric)
    active_color_metric = route_color_metric if color_status == "ok" else ""
    color_domain = _route_color_domain(routes, active_color_metric) if active_color_metric else None
    chart = RouteMap(
        title=workout.title,
        subtitle=_route_chart_subtitle(workout, language=language),
        routes=routes,
        legend_title=_route_legend_title(routes, language=language),
        color_metric_label=_route_color_metric_label(active_color_metric, language=language) if active_color_metric else "",
        color_domain=color_domain,
        color_tick_format=metric_tick_format(active_color_metric) if active_color_metric else "number",
        color_direction=metric_direction(active_color_metric) if active_color_metric else "ascending",
        width=render_size[0],
        height=render_size[1],
    )
    tile_data = _route_tiles(routes, tile_cache_root, maps_config=maps_config, width=chart.width, height=chart.height)
    renderer = resolve_renderer(renderers_config, "route")
    rendered = renderer.render_route_map_png(
        RouteMap(
            title=chart.title,
            subtitle=chart.subtitle,
            legend_title=chart.legend_title,
            color_metric_label=chart.color_metric_label,
            color_domain=chart.color_domain,
            color_tick_format=chart.color_tick_format,
            color_direction=chart.color_direction,
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
    )
    return VisualizationArtifact(
        content=rendered,
        filename=f"{filename_prefix}-route-map.png",
        content_type="image/png",
        rendered_metrics=("route", active_color_metric) if active_color_metric else ("route",),
        missing_metrics=(),
        scaled_metrics=(),
        metadata={
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
        },
    )


def _route_tiles(
    routes: tuple[RoutePolyline, ...],
    tile_cache_root: Path | None,
    *,
    maps_config: MapsConfig | None = None,
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
) -> dict[str, Any]:
    viewport = route_map_viewport(routes, width=width, height=height)
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
            color_values = _route_metric_values(route_points, route_color_metric)
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
                )
            )
    return tuple(routes)


def _is_route_color_metric_supported(metric: str) -> bool:
    return metric in {"heart_rate_bpm", "elevation_m", "pace_s_per_km"}


def _route_color_status(routes: tuple[RoutePolyline, ...], *, route_color_metric: str) -> str:
    if not route_color_metric:
        return "none"
    values = tuple(point.color_value for route in routes for point in route.points if point.color_value is not None)
    if len(values) < 2:
        return "missing_data"
    return "ok"


def _route_color_domain(routes: tuple[RoutePolyline, ...], metric: str) -> tuple[float, float] | None:
    values = tuple(point.color_value for route in routes for point in route.points if point.color_value is not None)
    return visual_domain(metric, values)


def _route_metric_values(points: list[WorkoutPointRecord], metric: str) -> tuple[float | None, ...]:
    if not metric:
        return tuple(None for _ in points)
    return clean_metric_series(metric, tuple(_route_point_metric_value(point, metric) for point in points))


def _route_point_metric_value(point: WorkoutPointRecord, metric: str) -> float | None:
    if metric == "heart_rate_bpm":
        return point.heart_rate_bpm
    if metric == "elevation_m":
        return point.elevation_m
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
    renderers_config: RenderersConfig | None = None,
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
        renderer = resolve_renderer(renderers_config, "bar")
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
        renderer = resolve_renderer(renderers_config, "pie")
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
        renderer = resolve_renderer(renderers_config, "bar")
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
        renderer = resolve_renderer(renderers_config, "multi_panel_line")
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
    renderer = resolve_renderer(renderers_config, "line")
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


def _route_chart_subtitle(workout: WorkoutRecord, *, language: SupportedLanguage) -> str:
    parts = (
        _format_route_datetime(workout.start_time_local or workout.start_time_utc or workout.local_date),
        _format_number(workout.distance_km, suffix=" km", digits=1),
        _format_route_duration(workout.duration_s),
        _format_route_average_hr(workout.avg_hr_bpm, language=language),
    )
    return " - ".join(part for part in parts if part)


def _route_legend_title(routes: tuple[RoutePolyline, ...], *, language: SupportedLanguage) -> str:
    if len(routes) > 1:
        return "Treenit" if language == SupportedLanguage.FI else "Workouts"
    return "Reitti" if language == SupportedLanguage.FI else "Route"


def _route_color_metric_label(metric: str, *, language: SupportedLanguage) -> str:
    if language == SupportedLanguage.FI:
        labels = {
            "heart_rate_bpm": "Syke",
            "elevation_m": "Korkeus",
            "pace_s_per_km": "Vauhti (min/km)",
        }
        return labels.get(metric, _series_label(metric, language=language))
    labels = {
        "pace_s_per_km": "Pace (min/km)",
    }
    return labels.get(metric, _series_label(metric, language=language))


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
    return comparison not in {"", "none", "single"}


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
