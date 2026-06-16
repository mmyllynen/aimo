from __future__ import annotations


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
    "duration_s",
    "ascent_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "point_count",
}


def canonical_metric(value: str) -> str:
    return value.strip().lower()
