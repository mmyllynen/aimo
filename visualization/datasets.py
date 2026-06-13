from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord
from visualization.metrics import canonical_metric


@dataclass(frozen=True)
class DatasetColumn:
    column_id: str
    unit: str = ""
    semantic_type: str = "quantitative"
    null_count: int = 0
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class Dataset:
    dataset_id: str
    rows: tuple[dict[str, Any], ...]
    columns: tuple[DatasetColumn, ...]


@dataclass(frozen=True)
class DatasetManifest:
    datasets: tuple[Dataset, ...]

    def dataset(self, dataset_id: str) -> Dataset | None:
        for dataset in self.datasets:
            if dataset.dataset_id == dataset_id:
                return dataset
        return None


@dataclass(frozen=True)
class DatasetRequest:
    metrics: tuple[str, ...]
    x_metric: str
    transforms: tuple[str, ...] = ()


@dataclass(frozen=True)
class DatasetDefinition:
    dataset_id: str
    output_columns: frozenset[str]
    build: Callable[[tuple[WorkoutPointRecord, ...], tuple[HeartRateZoneRecord, ...]], Dataset]


POINT_COLUMNS = (
    DatasetColumn("elapsed_s", unit="s"),
    DatasetColumn("distance_m", unit="m"),
    DatasetColumn("distance_km", unit="km"),
    DatasetColumn("latitude"),
    DatasetColumn("longitude"),
    DatasetColumn("elevation_m", unit="m"),
    DatasetColumn("heart_rate_bpm", unit="bpm"),
    DatasetColumn("cadence_spm", unit="spm"),
    DatasetColumn("pace_s_per_km", unit="s/km"),
)


DERIVED_DATASETS = (
    DatasetDefinition(
        dataset_id="hr_zone_distribution",
        output_columns=frozenset({"zone_key", "zone_label", "heart_rate_zone_seconds", "lower_bpm", "upper_bpm"}),
        build=lambda points, zones: _hr_zone_dataset(points, zones),
    ),
)


def dataset_request_from_metrics(
    *,
    x_metric: str,
    y_metrics: tuple[str, ...],
    transforms: tuple[str, ...],
) -> DatasetRequest:
    metrics = tuple(dict.fromkeys(canonical_metric(metric) for metric in y_metrics))
    return DatasetRequest(
        metrics=metrics,
        x_metric=canonical_metric(x_metric or "elapsed_s"),
        transforms=tuple(transform.strip().lower() for transform in transforms if transform.strip()),
    )


def resolve_datasets(
    request: DatasetRequest,
    *,
    points: tuple[WorkoutPointRecord, ...],
    heart_rate_zones: tuple[HeartRateZoneRecord, ...] = (),
) -> DatasetManifest:
    datasets = [_point_dataset(points)]
    requested = set(request.metrics)
    for definition in DERIVED_DATASETS:
        if requested & definition.output_columns:
            datasets.append(definition.build(points, heart_rate_zones))
    return DatasetManifest(datasets=tuple(datasets))


def _point_dataset(points: tuple[WorkoutPointRecord, ...]) -> Dataset:
    rows = tuple(
        {
            "elapsed_s": point.elapsed_s,
            "distance_m": point.distance_m,
            "distance_km": point.distance_km,
            "latitude": point.latitude,
            "longitude": point.longitude,
            "elevation_m": point.elevation_m,
            "heart_rate_bpm": point.heart_rate_bpm,
            "cadence_spm": point.cadence_spm,
            "pace_s_per_km": point.pace_s_per_km,
        }
        for point in points
    )
    return Dataset(
        dataset_id="workout_points",
        rows=rows,
        columns=tuple(_with_stats(column, rows) for column in POINT_COLUMNS),
    )


def _hr_zone_dataset(
    points: tuple[WorkoutPointRecord, ...],
    zones: tuple[HeartRateZoneRecord, ...],
) -> Dataset:
    seconds_by_zone = {zone.zone_key: 0.0 for zone in zones}
    for current, following in zip(points, points[1:], strict=False):
        heart_rate = current.heart_rate_bpm
        elapsed = current.elapsed_s
        next_elapsed = following.elapsed_s
        if heart_rate is None or elapsed is None or next_elapsed is None or next_elapsed <= elapsed:
            continue
        zone = _zone_for_heart_rate(heart_rate, zones)
        if zone is not None:
            seconds_by_zone[zone.zone_key] += next_elapsed - elapsed
    rows = tuple(
        {
            "zone_key": zone.zone_key,
            "zone_label": zone.label,
            "heart_rate_zone_seconds": seconds_by_zone[zone.zone_key],
            "lower_bpm": zone.lower_bpm,
            "upper_bpm": zone.upper_bpm,
        }
        for zone in zones
    )
    columns = (
        DatasetColumn("zone_label", semantic_type="nominal"),
        DatasetColumn("zone_key", semantic_type="nominal"),
        _with_stats(DatasetColumn("heart_rate_zone_seconds", unit="s"), rows),
        _with_stats(DatasetColumn("lower_bpm", unit="bpm"), rows),
        _with_stats(DatasetColumn("upper_bpm", unit="bpm"), rows),
    )
    return Dataset(dataset_id="hr_zone_distribution", rows=rows, columns=columns)


def _zone_for_heart_rate(
    heart_rate: float,
    zones: tuple[HeartRateZoneRecord, ...],
) -> HeartRateZoneRecord | None:
    for zone in zones:
        lower_ok = zone.lower_bpm is None or heart_rate >= zone.lower_bpm
        upper_ok = zone.upper_bpm is None or heart_rate <= zone.upper_bpm
        if lower_ok and upper_ok:
            return zone
    return None


def _with_stats(column: DatasetColumn, rows: tuple[dict[str, Any], ...]) -> DatasetColumn:
    values = tuple(row.get(column.column_id) for row in rows)
    numeric = tuple(value for value in values if isinstance(value, (int, float)))
    return DatasetColumn(
        column_id=column.column_id,
        unit=column.unit,
        semantic_type=column.semantic_type,
        null_count=sum(1 for value in values if value is None),
        min_value=min(numeric) if numeric else None,
        max_value=max(numeric) if numeric else None,
    )
