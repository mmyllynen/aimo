from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from storage.repositories import WorkoutEstimateFeatureRecord, WorkoutPointRecord, WorkoutRecord
from storage.unit_of_work import RepositoryBundle


CURRENT_FEATURE_VERSION = 1
GRADE_FLAT_LIMIT = 1.0
GRADE_STEEP_LIMIT = 8.0


def build_workout_estimate_features(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    *,
    updated_at: datetime | str | None = None,
) -> WorkoutEstimateFeatureRecord:
    distance_km = _distance_km(workout, points)
    elevations = tuple(point.elevation_m for point in points if point.elevation_m is not None)
    ascent_m, descent_m, longest_climb_m, longest_descent_m = _elevation_features(workout, points)
    grade_shares = _grade_shares(points)
    quality_flags = _quality_flags(workout, points, distance_km, elevations)
    location = _location_features(points)
    return WorkoutEstimateFeatureRecord(
        workout_id=workout.workout_id,
        owner_user_id=workout.owner_user_id,
        feature_version=CURRENT_FEATURE_VERSION,
        kind=workout.kind,
        primary_kind=workout.primary_kind,
        local_date=workout.local_date,
        distance_km=distance_km,
        duration_s=workout.duration_s,
        pace_s_per_km=_pace_s_per_km(workout, distance_km),
        ascent_m=ascent_m,
        descent_m=descent_m,
        ascent_per_km=_density(ascent_m, distance_km),
        descent_per_km=_density(descent_m, distance_km),
        elevation_min_m=min(elevations) if elevations else None,
        elevation_max_m=max(elevations) if elevations else None,
        flat_share=grade_shares["flat"],
        climb_share=grade_shares["climb"],
        steep_climb_share=grade_shares["steep_climb"],
        descent_share=grade_shares["descent"],
        steep_descent_share=grade_shares["steep_descent"],
        longest_climb_m=longest_climb_m,
        longest_descent_m=longest_descent_m,
        route_signature=_route_signature(workout, points, distance_km, ascent_m),
        distance_band=_distance_band(distance_km),
        ascent_band=_ascent_band(_density(ascent_m, distance_km)),
        point_count=len(points),
        distance_coverage=_coverage(points, "distance"),
        elevation_coverage=_coverage(points, "elevation"),
        gap_count=_gap_count(points),
        quality_flags=quality_flags,
        metadata={
            "feature_version": CURRENT_FEATURE_VERSION,
            "grade_flat_limit_percent": GRADE_FLAT_LIMIT,
            "grade_steep_limit_percent": GRADE_STEEP_LIMIT,
            "location": location,
        },
        updated_at=_timestamp(updated_at),
    )


def upsert_workout_estimate_features(
    repositories: RepositoryBundle,
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    *,
    updated_at: datetime | str | None = None,
) -> WorkoutEstimateFeatureRecord:
    record = build_workout_estimate_features(workout, points, updated_at=updated_at)
    return repositories.workout_estimate_features.upsert(record)


def backfill_workout_estimate_features(
    repositories: RepositoryBundle,
    *,
    owner_user_id: str | None = None,
    limit: int | None = None,
    updated_at: datetime | str | None = None,
) -> int:
    workouts = (
        repositories.workouts.list_for_user(owner_user_id, limit=limit or 100000)
        if owner_user_id is not None
        else _all_workouts(repositories, limit=limit)
    )
    count = 0
    for workout in workouts:
        points = repositories.workout_streams.list_points(workout.workout_id)
        upsert_workout_estimate_features(repositories, workout, points, updated_at=updated_at)
        count += 1
    return count


def _all_workouts(repositories: RepositoryBundle, *, limit: int | None) -> tuple[WorkoutRecord, ...]:
    return repositories.workouts.list_all(limit=limit or 100000)


def _distance_km(workout: WorkoutRecord, points: tuple[WorkoutPointRecord, ...]) -> float | None:
    if workout.distance_km is not None and workout.distance_km > 0:
        return float(workout.distance_km)
    point_values = tuple(point.distance_km for point in points if point.distance_km is not None)
    if len(point_values) >= 2 and point_values[-1] > point_values[0]:
        return float(point_values[-1] - point_values[0])
    point_meters = tuple(point.distance_m for point in points if point.distance_m is not None)
    if len(point_meters) >= 2 and point_meters[-1] > point_meters[0]:
        return float(point_meters[-1] - point_meters[0]) / 1000.0
    return None


def _pace_s_per_km(workout: WorkoutRecord, distance_km: float | None) -> float | None:
    if workout.pace_s_per_km is not None:
        return float(workout.pace_s_per_km)
    if workout.duration_s is None or distance_km is None or distance_km <= 0:
        return None
    return float(workout.duration_s) / distance_km


def _elevation_features(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
) -> tuple[float | None, float | None, float | None, float | None]:
    elevations = tuple(point.elevation_m for point in points if point.elevation_m is not None)
    if len(elevations) < 2:
        return workout.ascent_m, None, None, None
    ascent = 0.0
    descent = 0.0
    current_climb = 0.0
    current_descent = 0.0
    longest_climb = 0.0
    longest_descent = 0.0
    for current, following in zip(elevations, elevations[1:], strict=False):
        delta = following - current
        if delta > 1.0:
            ascent += delta
            current_climb += delta
            longest_climb = max(longest_climb, current_climb)
            current_descent = 0.0
        elif delta < -1.0:
            loss = abs(delta)
            descent += loss
            current_descent += loss
            longest_descent = max(longest_descent, current_descent)
            current_climb = 0.0
        else:
            current_climb = 0.0
            current_descent = 0.0
    return (
        workout.ascent_m if workout.ascent_m is not None else ascent,
        descent,
        longest_climb,
        longest_descent,
    )


def _grade_shares(points: tuple[WorkoutPointRecord, ...]) -> dict[str, float | None]:
    totals = {"flat": 0.0, "climb": 0.0, "steep_climb": 0.0, "descent": 0.0, "steep_descent": 0.0}
    total_distance_m = 0.0
    for current, following in zip(points, points[1:], strict=False):
        start_distance = _point_distance_m(current)
        end_distance = _point_distance_m(following)
        if start_distance is None or end_distance is None or end_distance <= start_distance:
            continue
        if current.elevation_m is None or following.elevation_m is None:
            continue
        distance_m = end_distance - start_distance
        grade = (following.elevation_m - current.elevation_m) / distance_m * 100.0
        total_distance_m += distance_m
        if grade <= -GRADE_STEEP_LIMIT:
            totals["steep_descent"] += distance_m
        elif grade < -GRADE_FLAT_LIMIT:
            totals["descent"] += distance_m
        elif grade < GRADE_FLAT_LIMIT:
            totals["flat"] += distance_m
        elif grade < GRADE_STEEP_LIMIT:
            totals["climb"] += distance_m
        else:
            totals["steep_climb"] += distance_m
    if total_distance_m <= 0:
        return {key: None for key in totals}
    return {key: value / total_distance_m for key, value in totals.items()}


def _point_distance_m(point: WorkoutPointRecord) -> float | None:
    if point.distance_m is not None:
        return float(point.distance_m)
    if point.distance_km is not None:
        return float(point.distance_km) * 1000.0
    return None


def _density(value: float | None, distance_km: float | None) -> float | None:
    if value is None or distance_km is None or distance_km <= 0:
        return None
    return value / distance_km


def _distance_band(distance_km: float | None) -> str:
    if distance_km is None:
        return "unknown"
    if distance_km < 5:
        return "0-5"
    if distance_km < 10:
        return "5-10"
    if distance_km < 21.1:
        return "10-21"
    if distance_km < 42.2:
        return "21-42"
    return "42+"


def _ascent_band(ascent_per_km: float | None) -> str:
    if ascent_per_km is None:
        return "unknown"
    if ascent_per_km < 5:
        return "flat"
    if ascent_per_km < 15:
        return "rolling"
    if ascent_per_km < 30:
        return "hilly"
    return "mountain"


def _coverage(points: tuple[WorkoutPointRecord, ...], key: str) -> float | None:
    if not points:
        return None
    if key == "distance":
        count = sum(1 for point in points if point.distance_km is not None or point.distance_m is not None)
    elif key == "elevation":
        count = sum(1 for point in points if point.elevation_m is not None)
    else:
        return None
    return count / len(points)


def _gap_count(points: tuple[WorkoutPointRecord, ...]) -> int:
    gaps = 0
    for current, following in zip(points, points[1:], strict=False):
        if current.elapsed_s is not None and following.elapsed_s is not None and following.elapsed_s - current.elapsed_s > 900:
            gaps += 1
        current_distance = _point_distance_m(current)
        following_distance = _point_distance_m(following)
        if current_distance is not None and following_distance is not None and following_distance - current_distance > 5000:
            gaps += 1
    return gaps


def _quality_flags(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    distance_km: float | None,
    elevations: tuple[float, ...],
) -> tuple[str, ...]:
    flags = []
    if not points:
        flags.append("missing_points")
    elif len(points) < 10:
        flags.append("low_point_count")
    if distance_km is None:
        flags.append("missing_distance")
    if not elevations:
        flags.append("missing_elevation")
    elif len(elevations) < len(points) * 0.8:
        flags.append("partial_elevation")
    if workout.duration_s is None:
        flags.append("missing_duration")
    return tuple(flags)


def _route_signature(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    distance_km: float | None,
    ascent_m: float | None,
) -> str:
    coordinates = tuple((point.latitude, point.longitude) for point in points if point.latitude is not None and point.longitude is not None)
    if len(coordinates) < 2:
        return ""
    step = max(1, len(coordinates) // 24)
    sampled = coordinates[::step]
    if sampled[-1] != coordinates[-1]:
        sampled = (*sampled, coordinates[-1])
    shape = "|".join(f"{lat:.4f},{lon:.4f}" for lat, lon in sampled)
    payload = f"{workout.owner_user_id}|{distance_km or 0:.1f}|{ascent_m or 0:.0f}|{shape}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _location_features(points: tuple[WorkoutPointRecord, ...]) -> dict[str, object]:
    coordinates = tuple((point.latitude, point.longitude) for point in points if point.latitude is not None and point.longitude is not None)
    if not coordinates:
        return {}
    latitudes = tuple(float(lat) for lat, _ in coordinates)
    longitudes = tuple(float(lon) for _, lon in coordinates)
    return {
        "centroid_latitude": sum(latitudes) / len(latitudes),
        "centroid_longitude": sum(longitudes) / len(longitudes),
        "start_latitude": latitudes[0],
        "start_longitude": longitudes[0],
        "end_latitude": latitudes[-1],
        "end_longitude": longitudes[-1],
        "min_latitude": min(latitudes),
        "max_latitude": max(latitudes),
        "min_longitude": min(longitudes),
        "max_longitude": max(longitudes),
    }


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        return value
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
