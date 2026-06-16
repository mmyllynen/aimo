from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from llm.operations import VisualizationIntent
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from visualization.datasets import Dataset, dataset_request_from_metrics, resolve_datasets
from visualization.render import (
    Bar,
    BarChart,
    LineChart,
    LinePanel,
    MultiPanelLineChart,
    PieChart,
    PieSlice,
    RenderSeries,
    render_bar_chart_png,
    render_line_chart_png,
    render_multi_panel_line_chart_png,
    render_pie_chart_png,
)
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


@dataclass(frozen=True)
class VisualizationValidationContext:
    dataset_manifest: dict[str, Any]
    validation_errors: tuple[dict[str, Any], ...]
    allowed_primitives: dict[str, Any]


class VisualizationError(ValueError):
    pass


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
) -> VisualizationArtifact:
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
    rendered = _render_spec(workout, spec, dataset, layout_mode=layout_mode)
    return VisualizationArtifact(
        content=rendered,
        filename=f"{workout.workout_id}-{spec.output_filename_suffix}.png",
        content_type="image/png",
        rendered_metrics=tuple(encoding.column_id for encoding in spec.y),
        missing_metrics=(),
        scaled_metrics=_scaled_metrics(spec, layout_mode),
    )


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


def _render_spec(workout: WorkoutRecord, spec: VisualizationSpec, dataset: Dataset, *, layout_mode: str = "single_axis") -> bytes:
    rows = _transformed_rows(spec, dataset)
    chart_title = _chart_title(workout.title, spec, dataset)
    chart_subtitle = _chart_subtitle(workout)
    x_label = _metric_label(spec.x.column_id)
    y_label = _y_axis_label(spec)
    if _should_render_metric_aggregate_bars(spec, dataset):
        return render_bar_chart_png(
            BarChart(
                title=chart_title,
                subtitle=chart_subtitle,
                x_label="Metric",
                y_label=y_label,
                y_tick_format=_y_tick_format(spec.y[0].column_id) if len(spec.y) == 1 else "number",
                bars=_aggregate_bars(spec, rows),
            )
        )
    if spec.mark == "pie":
        return render_pie_chart_png(
            PieChart(
                title=chart_title,
                subtitle=chart_subtitle,
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
        )
    if spec.mark == "bar":
        return render_bar_chart_png(
            BarChart(
                title=chart_title,
                subtitle=chart_subtitle,
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
        )
    series = tuple(
        RenderSeries(
            metric=encoding.column_id,
            values=tuple(_optional_numeric(row.get(encoding.column_id)) for row in rows),
            label=_series_label(encoding.column_id),
        )
        for encoding in spec.y
    )
    if "smooth" in spec.transforms or "rolling_average" in spec.transforms:
        series = _apply_rolling_average(series)
    if _should_normalize_to_primary_range(spec, layout_mode):
        series = _apply_normalization(series)
    if layout_mode == "small_multiples" and len(series) > 1:
        return render_multi_panel_line_chart_png(
            MultiPanelLineChart(
                title=chart_title,
                subtitle=chart_subtitle,
                x_label=x_label,
                x_tick_format=_tick_format(spec.x.column_id),
                x_values=tuple(_optional_numeric(row.get(spec.x.column_id)) for row in rows),
                panels=tuple(
                    LinePanel(
                        series=current,
                        y_label=_metric_label(current.metric),
                        y_tick_format=_y_tick_format(current.metric),
                        invert_y=_invert_y_axis(current.metric),
                    )
                    for current in series
                ),
            )
        )
    return render_line_chart_png(
        LineChart(
            title=chart_title,
            subtitle=chart_subtitle,
            x_label=x_label,
            y_label=y_label,
            x_tick_format=_tick_format(spec.x.column_id),
            y_tick_format=_y_tick_format(spec.y[0].column_id) if len(spec.y) == 1 else "number",
            invert_y=_invert_y_axis(spec.y[0].column_id) if len(spec.y) == 1 else False,
            x_values=tuple(_optional_numeric(row.get(spec.x.column_id)) for row in rows),
            series=series,
        )
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


def _chart_title(workout_title: str, spec: VisualizationSpec, dataset: Dataset | None = None) -> str:
    if len(spec.y) > 1:
        return f"Workout metrics - {workout_title}"
    if dataset is not None and "as_percentage_of_total" in spec.transforms:
        x_column = _column_semantic_type(dataset, spec.x.column_id)
        if x_column in {"nominal", "ordinal"}:
            return f"{_series_label(spec.x.column_id)} share - {workout_title}"
    metric = _metric_label(spec.y[0].column_id) if spec.y else "Chart"
    return f"{metric} - {workout_title}"


def _column_semantic_type(dataset: Dataset, column_id: str) -> str:
    column = next((candidate for candidate in dataset.columns if candidate.column_id == column_id), None)
    return column.semantic_type if column is not None else ""


def _chart_subtitle(workout: WorkoutRecord) -> str:
    parts = (
        _format_date(workout.local_date),
        _format_kind(workout.primary_kind or workout.kind),
        _format_number(workout.distance_km, suffix=" km", digits=1),
        _format_duration(workout.duration_s),
        _format_number(workout.avg_hr_bpm, prefix="avg ", suffix=" bpm", digits=0),
    )
    return " - ".join(part for part in parts if part)


def _y_axis_label(spec: VisualizationSpec) -> str:
    if "as_percentage_of_total" in spec.transforms:
        return "Share of total (%)"
    if len(spec.y) == 1:
        return _metric_label(spec.y[0].column_id)
    return "Value"


def _bar_tick_format(spec: VisualizationSpec) -> str:
    if "as_percentage_of_total" in spec.transforms:
        return "percentage"
    return _y_tick_format(spec.y[0].column_id)


def _metric_label(metric: str) -> str:
    labels = {
        "elapsed_s": "Time",
        "distance_m": "Distance (m)",
        "distance_km": "Distance (km)",
        "latitude": "Latitude",
        "longitude": "Longitude",
        "elevation_m": "Elevation (m)",
        "heart_rate_bpm": "Heart rate (bpm)",
        "cadence_spm": "Cadence (spm)",
        "pace_s_per_km": "Pace (min/km)",
        "heart_rate_zone_seconds": "Time in zone (s)",
        "zone_label": "Zone",
        "zone_key": "Zone",
        "duration_s": "Duration",
        "ascent_m": "Ascent (m)",
        "avg_hr_bpm": "Average HR (bpm)",
        "max_hr_bpm": "Max HR (bpm)",
        "point_count": "Point count",
    }
    return labels.get(metric, metric.replace("_", " ").title())


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
    units = {
        "elapsed_s": "time",
        "duration_s": "time",
        "heart_rate_zone_seconds": "time",
        "distance_m": "distance_m",
        "distance_km": "distance_km",
        "latitude": "coordinate",
        "longitude": "coordinate",
        "elevation_m": "elevation_m",
        "ascent_m": "elevation_m",
        "heart_rate_bpm": "heart_rate_bpm",
        "avg_hr_bpm": "heart_rate_bpm",
        "max_hr_bpm": "heart_rate_bpm",
        "cadence_spm": "cadence_spm",
        "pace_s_per_km": "time_per_distance",
        "point_count": "count",
    }
    return units.get(metric, metric)


def _series_label(metric: str) -> str:
    return _metric_label(metric).split(" (", 1)[0]


def _tick_format(metric: str) -> str:
    return "duration" if _metric_unit(metric) == "time" else "number"


def _y_tick_format(metric: str) -> str:
    return "pace" if metric == "pace_s_per_km" else _tick_format(metric)


def _invert_y_axis(metric: str) -> bool:
    return _metric_unit(metric) == "time_per_distance"


def _format_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    total_seconds = int(round(value))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


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
