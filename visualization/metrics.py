from __future__ import annotations


METRIC_ALIASES = {
    "sykealue": "heart_rate_zone_seconds",
    "sykealuejakauma": "heart_rate_zone_seconds",
    "sykevyöhyke": "heart_rate_zone_seconds",
    "heart_rate_zone": "heart_rate_zone_seconds",
    "hr_zone": "heart_rate_zone_seconds",
    "syke": "heart_rate_bpm",
    "heart_rate": "heart_rate_bpm",
    "hr": "heart_rate_bpm",
    "vauhti": "pace_s_per_km",
    "pace": "pace_s_per_km",
    "korkeus": "elevation_m",
    "maasto": "elevation_m",
    "elevation": "elevation_m",
    "altitude": "elevation_m",
    "aika": "elapsed_s",
    "time": "elapsed_s",
    "matka": "distance_km",
    "distance": "distance_km",
    "kadenssi": "cadence_spm",
    "cadence": "cadence_spm",
}

DEFAULT_X_METRIC = "elapsed_s"
DEFAULT_Y_METRICS = ("heart_rate_bpm",)
CANONICAL_POINT_METRICS = {
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
}


def canonical_metric(value: str) -> str:
    normalized = value.strip().lower()
    return METRIC_ALIASES.get(normalized, normalized)


def infer_metrics_from_text(text: str) -> tuple[str, ...]:
    normalized = text.lower()
    matches: list[tuple[int, int, str]] = []
    for alias, metric in METRIC_ALIASES.items():
        start = normalized.find(alias)
        if start >= 0 and metric != DEFAULT_X_METRIC:
            matches.append((start, -len(alias), metric))
    occupied: set[int] = set()
    metrics: list[str] = []
    for start, negative_length, metric in sorted(matches):
        span = set(range(start, start - negative_length))
        if occupied & span:
            continue
        occupied.update(span)
        if metric not in metrics:
            metrics.append(metric)
    return tuple(metrics or DEFAULT_Y_METRICS)


def infer_x_metric_from_text(text: str) -> str:
    normalized = text.lower()
    if "matka" in normalized or "distance" in normalized:
        return "distance_km"
    return DEFAULT_X_METRIC


def infer_transforms_from_text(text: str) -> tuple[str, ...]:
    normalized = text.lower()
    if "skaal" in normalized or "same range" in normalized or "normalize" in normalized:
        return ("normalize_to_primary_range",)
    return ()
