from __future__ import annotations

import math
from dataclasses import dataclass


CANONICAL_METRICS = {
    "elapsed_s",
    "distance_m",
    "distance_km",
    "latitude",
    "longitude",
    "elevation_m",
    "heart_rate_bpm",
    "cadence_spm",
    "pace_s_per_km",
    "heart_rate_zone_seconds",
    "route",
    "duration_s",
    "ascent_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "point_count",
}


@dataclass(frozen=True)
class MetricProfile:
    metric: str
    unit: str = ""
    display_unit: str = ""
    tick_format: str = "number"
    direction: str = "ascending"
    clean_policy: str = "none"
    domain_policy: str = "min_max"
    valid_min: float | None = None
    valid_max: float | None = None
    smoothing_window: int = 1
    quantile_low: float = 0.0
    quantile_high: float = 1.0


METRIC_PROFILES = {
    "elapsed_s": MetricProfile("elapsed_s", unit="s", display_unit="s", tick_format="duration"),
    "duration_s": MetricProfile("duration_s", unit="s", display_unit="s", tick_format="duration"),
    "heart_rate_zone_seconds": MetricProfile("heart_rate_zone_seconds", unit="s", display_unit="s", tick_format="duration"),
    "distance_m": MetricProfile("distance_m", unit="m", display_unit="m"),
    "distance_km": MetricProfile("distance_km", unit="km", display_unit="km"),
    "latitude": MetricProfile("latitude"),
    "longitude": MetricProfile("longitude"),
    "elevation_m": MetricProfile("elevation_m", unit="m", display_unit="m"),
    "ascent_m": MetricProfile("ascent_m", unit="m", display_unit="m"),
    "heart_rate_bpm": MetricProfile("heart_rate_bpm", unit="bpm", display_unit="bpm"),
    "avg_hr_bpm": MetricProfile("avg_hr_bpm", unit="bpm", display_unit="bpm"),
    "max_hr_bpm": MetricProfile("max_hr_bpm", unit="bpm", display_unit="bpm"),
    "cadence_spm": MetricProfile("cadence_spm", unit="spm", display_unit="spm"),
    "pace_s_per_km": MetricProfile(
        "pace_s_per_km",
        unit="s/km",
        display_unit="min/km",
        tick_format="pace",
        direction="descending",
        clean_policy="rolling_median",
        domain_policy="robust_quantile",
        valid_min=120.0,
        valid_max=1800.0,
        smoothing_window=5,
        quantile_low=0.05,
        quantile_high=0.95,
    ),
    "point_count": MetricProfile("point_count", unit="count", display_unit="count"),
}


def canonical_metric(value: str) -> str:
    return value.strip().lower()


def metric_profile(metric: str) -> MetricProfile:
    normalized = canonical_metric(metric)
    return METRIC_PROFILES.get(normalized, MetricProfile(normalized))


def metric_unit(metric: str) -> str:
    profile = metric_profile(metric)
    if profile.metric == "pace_s_per_km":
        return "time_per_distance"
    if profile.metric in {"elapsed_s", "duration_s", "heart_rate_zone_seconds"}:
        return "time"
    if profile.metric in {"distance_m", "distance_km"}:
        return profile.metric
    if profile.metric in {"latitude", "longitude"}:
        return "coordinate"
    if profile.metric in {"elevation_m", "ascent_m"}:
        return "elevation_m"
    if profile.metric in {"heart_rate_bpm", "avg_hr_bpm", "max_hr_bpm"}:
        return "heart_rate_bpm"
    return profile.display_unit or profile.unit or profile.metric


def metric_tick_format(metric: str) -> str:
    return metric_profile(metric).tick_format


def metric_direction(metric: str) -> str:
    return metric_profile(metric).direction


def metric_invert_axis(metric: str) -> bool:
    return metric_direction(metric) == "descending"


def clean_metric_series(metric: str, values: tuple[float | None, ...]) -> tuple[float | None, ...]:
    profile = metric_profile(metric)
    sanitized = tuple(_valid_metric_value(value, profile) for value in values)
    if profile.clean_policy == "rolling_median" and profile.smoothing_window > 1:
        return _rolling_median(sanitized, window=profile.smoothing_window)
    return sanitized


def visual_domain(metric: str, values: tuple[float | None, ...]) -> tuple[float, float] | None:
    numeric = tuple(value for value in values if value is not None and math.isfinite(value))
    if not numeric:
        return None
    profile = metric_profile(metric)
    if profile.domain_policy == "robust_quantile" and len(numeric) >= 4:
        low = _quantile(numeric, profile.quantile_low)
        high = _quantile(numeric, profile.quantile_high)
    else:
        low = min(numeric)
        high = max(numeric)
    if low == high:
        padding = max(abs(low) * 0.05, 1.0)
        return low - padding, high + padding
    return low, high


def color_ratio_for_metric(metric: str, value: float, domain: tuple[float, float]) -> float:
    low, high = domain
    if high <= low:
        ratio = 0.5
    else:
        ratio = (value - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    if metric_direction(metric) == "descending":
        return 1.0 - ratio
    return ratio


def _valid_metric_value(value: float | None, profile: MetricProfile) -> float | None:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    numeric = float(value)
    if profile.valid_min is not None and numeric < profile.valid_min:
        return None
    if profile.valid_max is not None and numeric > profile.valid_max:
        return None
    return numeric


def _rolling_median(values: tuple[float | None, ...], *, window: int) -> tuple[float | None, ...]:
    radius = max(0, window // 2)
    smoothed: list[float | None] = []
    for index, value in enumerate(values):
        if value is None:
            smoothed.append(None)
            continue
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        nearby = sorted(candidate for candidate in values[start:end] if candidate is not None)
        smoothed.append(_median(nearby) if nearby else None)
    return tuple(smoothed)


def _median(values: list[float]) -> float:
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _quantile(values: tuple[float, ...], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = max(0.0, min(1.0, ratio)) * (len(ordered) - 1)
    low_index = int(math.floor(position))
    high_index = int(math.ceil(position))
    if low_index == high_index:
        return ordered[low_index]
    local = position - low_index
    return ordered[low_index] + (ordered[high_index] - ordered[low_index]) * local
