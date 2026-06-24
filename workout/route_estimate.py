from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import exp, log
from statistics import median

from storage.repositories import WorkoutEstimateFeatureRecord, WorkoutPointRecord, WorkoutRecord


@dataclass(frozen=True)
class RouteTimeEstimate:
    estimate_s: float
    low_s: float
    high_s: float
    confidence: str
    comparable_count: int
    route_distance_km: float
    route_ascent_m: float | None
    baseline_pace_s_per_km: float
    ascent_penalty_s: float
    distance_adjustment_s: float
    missing_data: tuple[str, ...] = ()
    model: str = "summary_median"
    similarity: dict[str, object] | None = None
    explanation: dict[str, object] | None = None


@dataclass(frozen=True)
class WeightedFeature:
    feature: WorkoutEstimateFeatureRecord
    weight: float
    distance_score: float
    ascent_score: float
    grade_score: float
    recency_score: float
    kind_score: float


def estimate_route_time(
    target: WorkoutRecord,
    target_points: tuple[WorkoutPointRecord, ...],
    history: tuple[WorkoutRecord, ...],
) -> RouteTimeEstimate | None:
    distance_km = _route_distance_km(target, target_points)
    if distance_km is None or distance_km <= 0:
        return None
    ascent_m = _route_ascent_m(target, target_points)
    comparable = _comparable_workouts(target, history)
    pace_values = tuple(workout.duration_s / workout.distance_km for workout in comparable if workout.duration_s and workout.distance_km and workout.distance_km > 0)
    if pace_values:
        baseline_pace = median(pace_values)
    elif target.pace_s_per_km is not None:
        baseline_pace = float(target.pace_s_per_km)
    else:
        baseline_pace = 420.0
    ascent_penalty_rate = _ascent_penalty_rate(comparable)
    ascent_penalty = max(0.0, (ascent_m or 0.0) * ascent_penalty_rate)
    distance_adjustment = _distance_adjustment(distance_km, comparable)
    estimate = max(60.0, distance_km * baseline_pace + ascent_penalty + distance_adjustment)
    confidence = _confidence(comparable, target_points, ascent_m)
    spread = _uncertainty_spread(confidence)
    missing = []
    if not comparable:
        missing.append("user_history")
    if ascent_m is None:
        missing.append("ascent_m")
    if not target_points:
        missing.append("route_points")
    return RouteTimeEstimate(
        estimate_s=estimate,
        low_s=max(60.0, estimate * (1.0 - spread)),
        high_s=estimate * (1.0 + spread),
        confidence=confidence,
        comparable_count=len(comparable),
        route_distance_km=distance_km,
        route_ascent_m=ascent_m,
        baseline_pace_s_per_km=baseline_pace,
        ascent_penalty_s=ascent_penalty,
        distance_adjustment_s=distance_adjustment,
        missing_data=tuple(missing),
        explanation=_explanation_payload(
            model="summary_median",
            baseline_pace_s_per_km=baseline_pace,
            ascent_penalty_s=ascent_penalty,
            distance_adjustment_s=distance_adjustment,
            uncertainty_source=f"fixed_confidence_{confidence}",
        ),
    )


def estimate_route_time_from_features(
    target: WorkoutRecord,
    target_feature: WorkoutEstimateFeatureRecord | None,
    target_points: tuple[WorkoutPointRecord, ...],
    history_features: tuple[WorkoutEstimateFeatureRecord, ...],
    history: tuple[WorkoutRecord, ...],
) -> RouteTimeEstimate | None:
    if target_feature is None:
        return estimate_route_time(target, target_points, history)
    distance_km = target_feature.distance_km
    if distance_km is None or distance_km <= 0:
        return estimate_route_time(target, target_points, history)
    ascent_m = target_feature.ascent_m
    weighted = _weighted_feature_records(target_feature, history_features)
    comparable = tuple(item.feature for item in weighted)
    pace_values = tuple(
        feature.duration_s / feature.distance_km
        for feature in comparable
        if feature.duration_s and feature.distance_km and feature.distance_km > 0
    )
    if pace_values:
        baseline_pace = _weighted_median(
            tuple(
                (item.feature.duration_s / item.feature.distance_km, item.weight)
                for item in weighted
                if item.feature.duration_s and item.feature.distance_km and item.feature.distance_km > 0
            )
        )
    elif target_feature.pace_s_per_km is not None:
        baseline_pace = float(target_feature.pace_s_per_km)
    elif target.pace_s_per_km is not None:
        baseline_pace = float(target.pace_s_per_km)
    else:
        baseline_pace = 420.0
    ascent_penalty_rate = _feature_ascent_penalty_rate(weighted)
    ascent_penalty = max(0.0, (ascent_m or 0.0) * ascent_penalty_rate)
    distance_adjustment = _feature_distance_adjustment(distance_km, weighted)
    estimate = max(60.0, distance_km * baseline_pace + ascent_penalty + distance_adjustment)
    confidence = _feature_confidence(weighted, target_feature)
    spread, uncertainty_source = _feature_uncertainty_spread(weighted, confidence, target_feature)
    missing = []
    if not comparable:
        missing.append("user_history")
    if ascent_m is None:
        missing.append("ascent_m")
    if target_feature.point_count <= 0:
        missing.append("route_points")
    missing.extend(f"quality:{flag}" for flag in _route_relevant_quality_flags(target_feature))
    return RouteTimeEstimate(
        estimate_s=estimate,
        low_s=max(60.0, estimate * (1.0 - spread)),
        high_s=estimate * (1.0 + spread),
        confidence=confidence,
        comparable_count=len(comparable),
        route_distance_km=distance_km,
        route_ascent_m=ascent_m,
        baseline_pace_s_per_km=baseline_pace,
        ascent_penalty_s=ascent_penalty,
        distance_adjustment_s=distance_adjustment,
        missing_data=tuple(dict.fromkeys(missing)),
        model="feature_similarity",
        similarity=_similarity_summary(target_feature, weighted),
        explanation=_explanation_payload(
            model="feature_similarity",
            baseline_pace_s_per_km=baseline_pace,
            ascent_penalty_s=ascent_penalty,
            distance_adjustment_s=distance_adjustment,
            uncertainty_source=uncertainty_source,
            effective_sample_size=_effective_sample_size(tuple(item.weight for item in weighted)),
        ),
    )


def format_route_time_estimate(estimate: RouteTimeEstimate, *, language: str = "fi") -> str:
    if language == "en":
        lines = [
            f"Estimated route time: {_format_duration_words(estimate.estimate_s)}",
            f"Likely range: {_format_duration_words(estimate.low_s)} - {_format_duration_words(estimate.high_s)}",
            "",
            "Basis:",
            f"- distance {estimate.route_distance_km:.1f} km",
            f"- ascent {_format_ascent(estimate.route_ascent_m)}",
            f"- based on {estimate.comparable_count} comparable stored workout(s)",
            f"- confidence: {estimate.confidence}",
        ]
        if estimate.missing_data:
            lines.append(f"- missing/limited data: {', '.join(estimate.missing_data)}")
        return "\n".join(lines)
    lines = [
        f"Arvio tälle reitille: {_format_duration_words(estimate.estimate_s)}",
        f"Todennäköinen vaihteluväli: {_format_duration_words(estimate.low_s)} - {_format_duration_words(estimate.high_s)}",
        "",
        "Perusteet:",
        f"- matka {estimate.route_distance_km:.1f} km",
        f"- nousua {_format_ascent(estimate.route_ascent_m)}",
        f"- perustuu {estimate.comparable_count} tallennettuun vertailutreeniin",
        f"- varmuus: {_confidence_fi(estimate.confidence)}",
    ]
    if estimate.missing_data:
        lines.append(f"- puuttuvaa/rajallista dataa: {', '.join(estimate.missing_data)}")
    return "\n".join(lines)


def _route_distance_km(workout: WorkoutRecord, points: tuple[WorkoutPointRecord, ...]) -> float | None:
    if workout.distance_km is not None and workout.distance_km > 0:
        return float(workout.distance_km)
    point_distances = tuple(point.distance_km for point in points if point.distance_km is not None)
    if len(point_distances) >= 2 and point_distances[-1] > point_distances[0]:
        return float(point_distances[-1] - point_distances[0])
    point_distances_m = tuple(point.distance_m for point in points if point.distance_m is not None)
    if len(point_distances_m) >= 2 and point_distances_m[-1] > point_distances_m[0]:
        return float(point_distances_m[-1] - point_distances_m[0]) / 1000.0
    return None


def _route_ascent_m(workout: WorkoutRecord, points: tuple[WorkoutPointRecord, ...]) -> float | None:
    if workout.ascent_m is not None:
        return max(0.0, float(workout.ascent_m))
    elevations = tuple(point.elevation_m for point in points if point.elevation_m is not None)
    if len(elevations) < 2:
        return None
    ascent = 0.0
    for current, following in zip(elevations, elevations[1:], strict=False):
        delta = following - current
        if delta > 1.0:
            ascent += delta
    return ascent


def _comparable_workouts(target: WorkoutRecord, history: tuple[WorkoutRecord, ...]) -> tuple[WorkoutRecord, ...]:
    same_kind = tuple(workout for workout in history if _usable_history_workout(target, workout) and workout.primary_kind == target.primary_kind)
    if len(same_kind) >= 3:
        return same_kind[:30]
    return tuple(workout for workout in history if _usable_history_workout(target, workout))[:30]


def _comparable_feature_records(
    target: WorkoutEstimateFeatureRecord,
    features: tuple[WorkoutEstimateFeatureRecord, ...],
) -> tuple[WorkoutEstimateFeatureRecord, ...]:
    usable = tuple(feature for feature in features if _usable_feature_record(target, feature))
    same_kind = tuple(feature for feature in usable if feature.primary_kind == target.primary_kind)
    if len(same_kind) >= 3:
        return same_kind[:30]
    same_band = tuple(feature for feature in usable if feature.distance_band == target.distance_band and feature.ascent_band == target.ascent_band)
    if len(same_band) >= 3:
        return same_band[:30]
    return usable[:30]


def _weighted_feature_records(
    target: WorkoutEstimateFeatureRecord,
    features: tuple[WorkoutEstimateFeatureRecord, ...],
) -> tuple[WeightedFeature, ...]:
    weighted = []
    for feature in features:
        if not _usable_feature_record(target, feature):
            continue
        distance_score = _distance_similarity(target.distance_km, feature.distance_km)
        ascent_score = _ascent_similarity(target.ascent_per_km, feature.ascent_per_km)
        grade_score = _grade_similarity(target, feature)
        recency_score = _recency_similarity(target.local_date, feature.local_date)
        kind_score = 1.0 if feature.primary_kind == target.primary_kind else 0.65
        band_score = 1.15 if feature.distance_band == target.distance_band else 1.0
        ascent_band_score = 1.10 if feature.ascent_band == target.ascent_band else 1.0
        route_score = 1.25 if target.route_signature and feature.route_signature == target.route_signature else 1.0
        weight = max(0.05, distance_score * ascent_score * grade_score * recency_score * kind_score * band_score * ascent_band_score * route_score)
        weighted.append(
            WeightedFeature(
                feature=feature,
                weight=weight,
                distance_score=distance_score,
                ascent_score=ascent_score,
                grade_score=grade_score,
                recency_score=recency_score,
                kind_score=kind_score,
            )
        )
    return tuple(sorted(weighted, key=lambda item: item.weight, reverse=True)[:30])


def _usable_feature_record(target: WorkoutEstimateFeatureRecord, feature: WorkoutEstimateFeatureRecord) -> bool:
    return (
        feature.workout_id != target.workout_id
        and feature.duration_s is not None
        and feature.duration_s > 0
        and feature.distance_km is not None
        and feature.distance_km > 0
        and feature.primary_kind != "route"
        and feature.kind != "route_plan"
    )


def _usable_history_workout(target: WorkoutRecord, workout: WorkoutRecord) -> bool:
    return (
        workout.workout_id != target.workout_id
        and workout.duration_s is not None
        and workout.duration_s > 0
        and workout.distance_km is not None
        and workout.distance_km > 0
        and workout.primary_kind != "route"
        and workout.kind != "route_plan"
    )


def _feature_ascent_penalty_rate(weighted: tuple[WeightedFeature, ...]) -> float:
    with_ascent = tuple(item for item in weighted if item.feature.ascent_m is not None and item.feature.distance_km and item.feature.duration_s)
    if len(with_ascent) < 4:
        return 2.5
    flatish = tuple(
        (item.feature.duration_s / item.feature.distance_km, item.weight)
        for item in with_ascent
        if (item.feature.ascent_per_km or 0.0) < 8
    )
    hilly = tuple(
        (item.feature.duration_s / item.feature.distance_km, item.weight)
        for item in with_ascent
        if (item.feature.ascent_per_km or 0.0) >= 8
    )
    if not flatish or not hilly:
        return 2.5
    pace_delta = max(0.0, _weighted_median(hilly) - _weighted_median(flatish))
    ascent_density = _weighted_median(tuple((item.feature.ascent_per_km or 0.0, item.weight) for item in with_ascent if (item.feature.ascent_per_km or 0.0) >= 8))
    if ascent_density <= 0:
        return 2.5
    return max(1.0, min(8.0, pace_delta / ascent_density))


def _ascent_penalty_rate(workouts: tuple[WorkoutRecord, ...]) -> float:
    with_ascent = tuple(workout for workout in workouts if workout.ascent_m is not None and workout.distance_km and workout.duration_s)
    if len(with_ascent) < 4:
        return 2.5
    flatish = tuple(workout.duration_s / workout.distance_km for workout in with_ascent if (workout.ascent_m or 0.0) / workout.distance_km < 8)
    hilly = tuple(workout.duration_s / workout.distance_km for workout in with_ascent if (workout.ascent_m or 0.0) / workout.distance_km >= 8)
    if not flatish or not hilly:
        return 2.5
    pace_delta = max(0.0, median(hilly) - median(flatish))
    ascent_density = median(tuple((workout.ascent_m or 0.0) / workout.distance_km for workout in hilly))
    if ascent_density <= 0:
        return 2.5
    return max(1.0, min(8.0, pace_delta / ascent_density))


def _feature_distance_adjustment(distance_km: float, weighted: tuple[WeightedFeature, ...]) -> float:
    distances = tuple((item.feature.distance_km, item.weight) for item in weighted if item.feature.distance_km is not None)
    if len(distances) < 3:
        return 0.0
    typical = _weighted_median(distances)
    if typical <= 0 or distance_km <= typical:
        return 0.0
    return min(0.12, (distance_km / typical - 1.0) * 0.04) * distance_km * _weighted_median(
        tuple(
            (item.feature.duration_s / item.feature.distance_km, item.weight)
            for item in weighted
            if item.feature.duration_s and item.feature.distance_km
        )
    )


def _distance_adjustment(distance_km: float, workouts: tuple[WorkoutRecord, ...]) -> float:
    distances = tuple(workout.distance_km for workout in workouts if workout.distance_km is not None)
    if len(distances) < 3:
        return 0.0
    typical = median(distances)
    if typical <= 0 or distance_km <= typical:
        return 0.0
    return min(0.12, (distance_km / typical - 1.0) * 0.04) * distance_km * median(
        tuple(workout.duration_s / workout.distance_km for workout in workouts if workout.duration_s and workout.distance_km)
    )


def _feature_uncertainty_spread(
    weighted: tuple[WeightedFeature, ...],
    confidence: str,
    target: WorkoutEstimateFeatureRecord,
) -> tuple[float, str]:
    fallback = _uncertainty_spread(confidence)
    residuals = []
    paces = tuple(
        (item.feature.duration_s / item.feature.distance_km, item.weight)
        for item in weighted
        if item.feature.duration_s and item.feature.distance_km
    )
    if len(paces) < 4:
        return fallback, f"fixed_confidence_{confidence}"
    baseline_pace = _weighted_median(paces)
    for item in weighted:
        feature = item.feature
        if not feature.duration_s or not feature.distance_km:
            continue
        predicted = feature.distance_km * baseline_pace
        if feature.ascent_m is not None:
            predicted += max(0.0, feature.ascent_m * 2.5)
        if predicted <= 0:
            continue
        residuals.append((abs(feature.duration_s - predicted) / predicted, item.weight))
    if len(residuals) < 4:
        return fallback, f"fixed_confidence_{confidence}"
    residual_spread = _weighted_quantile(tuple(residuals), 0.75)
    quality_penalty = 0.03 if target.quality_flags else 0.0
    return max(0.10, min(0.40, max(fallback * 0.75, residual_spread + quality_penalty))), "weighted_residuals"


def _feature_confidence(weighted: tuple[WeightedFeature, ...], target: WorkoutEstimateFeatureRecord) -> str:
    effective = _effective_sample_size(tuple(item.weight for item in weighted))
    if effective >= 6 and len(weighted) >= 8 and target.point_count > 0 and target.ascent_m is not None:
        return "high"
    if effective >= 2.5 and len(weighted) >= 3:
        return "medium"
    return "low"


def _distance_similarity(target: float | None, candidate: float | None) -> float:
    if target is None or candidate is None or target <= 0 or candidate <= 0:
        return 0.55
    ratio = abs(log(candidate / target))
    return max(0.20, exp(-1.35 * ratio))


def _ascent_similarity(target: float | None, candidate: float | None) -> float:
    if target is None or candidate is None:
        return 0.70
    return max(0.25, exp(-abs(candidate - target) / 18.0))


def _grade_similarity(target: WorkoutEstimateFeatureRecord, candidate: WorkoutEstimateFeatureRecord) -> float:
    target_values = _grade_vector(target)
    candidate_values = _grade_vector(candidate)
    if target_values is None or candidate_values is None:
        return 0.80
    diff = sum(abs(left - right) for left, right in zip(target_values, candidate_values, strict=False))
    return max(0.30, 1.0 - diff / 2.0)


def _grade_vector(feature: WorkoutEstimateFeatureRecord) -> tuple[float, float, float, float, float] | None:
    values = (
        feature.flat_share,
        feature.climb_share,
        feature.steep_climb_share,
        feature.descent_share,
        feature.steep_descent_share,
    )
    if any(value is None for value in values):
        return None
    return tuple(float(value) for value in values if value is not None)


def _recency_similarity(target_date: str | None, candidate_date: str | None) -> float:
    if target_date is None or candidate_date is None:
        return 0.90
    try:
        age_days = abs((date.fromisoformat(target_date) - date.fromisoformat(candidate_date)).days)
    except ValueError:
        return 0.90
    return max(0.75, exp(-age_days / 730.0))


def _weighted_median(values: tuple[tuple[float, float], ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values, key=lambda item: item[0])
    total = sum(max(0.0, weight) for _, weight in ordered)
    if total <= 0:
        return median(tuple(value for value, _ in ordered))
    cumulative = 0.0
    midpoint = total / 2.0
    for value, weight in ordered:
        cumulative += max(0.0, weight)
        if cumulative >= midpoint:
            return value
    return ordered[-1][0]


def _weighted_quantile(values: tuple[tuple[float, float], ...], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values, key=lambda item: item[0])
    total = sum(max(0.0, weight) for _, weight in ordered)
    if total <= 0:
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
        return ordered[index][0]
    cumulative = 0.0
    threshold = total * quantile
    for value, weight in ordered:
        cumulative += max(0.0, weight)
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def _effective_sample_size(weights: tuple[float, ...]) -> float:
    total = sum(max(0.0, weight) for weight in weights)
    squared = sum(max(0.0, weight) ** 2 for weight in weights)
    if squared <= 0:
        return 0.0
    return total * total / squared


def _similarity_summary(target: WorkoutEstimateFeatureRecord, weighted: tuple[WeightedFeature, ...]) -> dict[str, object]:
    top = weighted[:5]
    return {
        "model": "feature_similarity",
        "candidate_count": len(weighted),
        "effective_sample_size": round(_effective_sample_size(tuple(item.weight for item in weighted)), 2),
        "target_distance_band": target.distance_band,
        "target_ascent_band": target.ascent_band,
        "top_weights": [round(item.weight, 3) for item in top],
        "top_distance_scores": [round(item.distance_score, 3) for item in top],
        "top_ascent_scores": [round(item.ascent_score, 3) for item in top],
        "top_grade_scores": [round(item.grade_score, 3) for item in top],
    }


def _explanation_payload(
    *,
    model: str,
    baseline_pace_s_per_km: float,
    ascent_penalty_s: float,
    distance_adjustment_s: float,
    uncertainty_source: str,
    effective_sample_size: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "baseline_pace_s_per_km": round(baseline_pace_s_per_km, 2),
        "baseline_pace_text": _format_pace(baseline_pace_s_per_km),
        "ascent_penalty_s": round(ascent_penalty_s),
        "ascent_penalty_text": _format_duration_words(ascent_penalty_s),
        "distance_adjustment_s": round(distance_adjustment_s),
        "distance_adjustment_text": _format_duration_words(distance_adjustment_s),
        "uncertainty_source": uncertainty_source,
    }
    if effective_sample_size is not None:
        payload["effective_sample_size"] = round(effective_sample_size, 2)
    return payload


def _route_relevant_quality_flags(feature: WorkoutEstimateFeatureRecord) -> tuple[str, ...]:
    ignored = {"missing_duration"} if feature.primary_kind == "route" or feature.kind == "route_plan" else set()
    return tuple(flag for flag in feature.quality_flags if flag not in ignored)


def _confidence(workouts: tuple[WorkoutRecord, ...], points: tuple[WorkoutPointRecord, ...], ascent_m: float | None) -> str:
    if len(workouts) >= 8 and points and ascent_m is not None:
        return "high"
    if len(workouts) >= 3:
        return "medium"
    return "low"


def _uncertainty_spread(confidence: str) -> float:
    return {"high": 0.12, "medium": 0.20}.get(confidence, 0.35)


def _format_duration_words(seconds: float) -> str:
    total_minutes = max(1, int(round(seconds / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min"


def _format_ascent(value: float | None) -> str:
    return "-" if value is None else f"{round(value)} m"


def _format_pace(seconds_per_km: float) -> str:
    total_seconds = max(1, int(round(seconds_per_km)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d} min/km"


def _confidence_fi(value: str) -> str:
    return {"high": "hyvä", "medium": "kohtalainen", "low": "heikko"}.get(value, value)
