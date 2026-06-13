from __future__ import annotations

from dataclasses import dataclass

from llm.operations import VisualizationIntent
from storage.repositories import WorkoutPointRecord, WorkoutRecord
from visualization.metrics import canonical_metric
from visualization.render import LineChart, RenderSeries, render_line_chart_png


SUPPORTED_TRANSFORMS = {"normalize_to_primary_range", "filter_non_null"}


@dataclass(frozen=True)
class VisualizationArtifact:
    content: bytes
    filename: str
    content_type: str
    rendered_metrics: tuple[str, ...]
    missing_metrics: tuple[str, ...]
    scaled_metrics: tuple[str, ...]


class VisualizationError(ValueError):
    pass


class MissingPrimaryMetricError(VisualizationError):
    def __init__(self, metric: str) -> None:
        self.metric = metric
        super().__init__(metric)


def render_workout_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
) -> VisualizationArtifact:
    x_metric = canonical_metric(intent.x_metric)
    y_metrics = tuple(canonical_metric(metric) for metric in intent.y_metrics)
    if not y_metrics:
        raise MissingPrimaryMetricError("metric")
    x_values = _values(points, x_metric)
    raw_series = tuple(RenderSeries(metric=metric, values=_values(points, metric)) for metric in y_metrics)
    missing = tuple(series.metric for series in raw_series if not any(value is not None for value in series.values))
    if raw_series[0].metric in missing:
        raise MissingPrimaryMetricError(raw_series[0].metric)
    available = tuple(series for series in raw_series if series.metric not in missing)
    scaled = _apply_normalization(available) if "normalize_to_primary_range" in intent.transforms else available
    content = render_line_chart_png(
        LineChart(
            title=workout.title,
            x_values=x_values,
            series=scaled,
        )
    )
    return VisualizationArtifact(
        content=content,
        filename=f"{workout.workout_id}-chart.png",
        content_type="image/png",
        rendered_metrics=tuple(series.metric for series in scaled),
        missing_metrics=missing,
        scaled_metrics=tuple(series.metric for series in scaled if series.scaled),
    )


def _values(points: tuple[WorkoutPointRecord, ...], metric: str) -> tuple[float | None, ...]:
    return tuple(_point_value(point, metric) for point in points)


def _point_value(point: WorkoutPointRecord, metric: str) -> float | None:
    value = getattr(point, metric, None)
    return value if isinstance(value, (int, float)) else None


def _apply_normalization(series: tuple[RenderSeries, ...]) -> tuple[RenderSeries, ...]:
    if len(series) <= 1:
        return series
    primary = series[0]
    target = _domain(primary.values)
    normalized = [primary]
    for current in series[1:]:
        source = _domain(current.values)
        normalized.append(
            RenderSeries(
                metric=current.metric,
                values=tuple(_normalize(value, source, target) for value in current.values),
                scaled=True,
            )
        )
    return tuple(normalized)


def _domain(values: tuple[float | None, ...]) -> tuple[float, float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return (0.0, 1.0)
    low = min(numeric)
    high = max(numeric)
    if low == high:
        return (low, high + 1.0)
    return (low, high)


def _normalize(value: float | None, source: tuple[float, float], target: tuple[float, float]) -> float | None:
    if value is None:
        return None
    source_low, source_high = source
    target_low, target_high = target
    return target_low + ((value - source_low) / (source_high - source_low)) * (target_high - target_low)
