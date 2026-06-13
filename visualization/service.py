from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm.operations import VisualizationIntent
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from visualization.datasets import Dataset, dataset_request_from_metrics, resolve_datasets
from visualization.render import Bar, BarChart, LineChart, RenderSeries, render_bar_chart_png, render_line_chart_png
from visualization.specs import (
    MissingRenderableDataError,
    VisualizationSpec,
    VisualizationSpecError,
    compile_visualization_spec,
)


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


class VisualizationSpecInvalidError(VisualizationError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def render_workout_visualization(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    intent: VisualizationIntent,
    *,
    heart_rate_zones: tuple[HeartRateZoneRecord, ...] = (),
) -> VisualizationArtifact:
    request = dataset_request_from_metrics(
        x_metric=intent.x_metric,
        y_metrics=intent.y_metrics,
        transforms=intent.transforms,
    )
    manifest = resolve_datasets(request, points=points, heart_rate_zones=heart_rate_zones)
    try:
        spec = compile_visualization_spec(request, manifest)
    except MissingRenderableDataError as exc:
        raise MissingPrimaryMetricError(exc.column_id) from exc
    except VisualizationSpecError as exc:
        raise VisualizationSpecInvalidError(type(exc).__name__) from exc

    dataset = manifest.dataset(spec.x.dataset_id)
    if dataset is None:
        raise VisualizationSpecInvalidError("DatasetNotFound")
    rendered = _render_spec(workout.title, spec, dataset)
    return VisualizationArtifact(
        content=rendered,
        filename=f"{workout.workout_id}-{spec.output_filename_suffix}.png",
        content_type="image/png",
        rendered_metrics=tuple(encoding.column_id for encoding in spec.y),
        missing_metrics=(),
        scaled_metrics=_scaled_metrics(spec),
    )


def _render_spec(title: str, spec: VisualizationSpec, dataset: Dataset) -> bytes:
    if spec.mark == "bar":
        return render_bar_chart_png(
            BarChart(
                title=title,
                bars=tuple(
                    Bar(label=str(row.get(spec.x.column_id, "")), value=_numeric(row.get(spec.y[0].column_id)))
                    for row in dataset.rows
                ),
            )
        )
    series = tuple(
        RenderSeries(
            metric=encoding.column_id,
            values=tuple(_optional_numeric(row.get(encoding.column_id)) for row in dataset.rows),
        )
        for encoding in spec.y
    )
    if "normalize_to_primary_range" in spec.transforms:
        series = _apply_normalization(series)
    return render_line_chart_png(
        LineChart(
            title=title,
            x_values=tuple(_optional_numeric(row.get(spec.x.column_id)) for row in dataset.rows),
            series=series,
        )
    )


def _scaled_metrics(spec: VisualizationSpec) -> tuple[str, ...]:
    if "normalize_to_primary_range" not in spec.transforms:
        return ()
    return tuple(encoding.column_id for encoding in spec.y[1:])


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
