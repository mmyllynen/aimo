from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from llm.operations import PERIOD_METRICS, PeriodRequest
from storage.repositories import WorkoutRecord


JsonObject = dict[str, Any]
DEFAULT_PERIOD_TIMEZONE = "Europe/Helsinki"
DEFAULT_PERIOD_METRICS = ("workout_count", "distance_km", "duration_s", "ascent_m")
SUMMARIZABLE_METRICS = tuple(metric for metric in PERIOD_METRICS if metric != "workout_count")
MAX_COMPACT_WORKOUTS = 30
MAX_GROUPS_FOR_LLM = 100


@dataclass(frozen=True)
class PeriodBounds:
    label: str
    start_date: str | None = None
    end_date: str | None = None


class PeriodRequestError(ValueError):
    pass


def local_now(value: datetime, timezone_name: str = DEFAULT_PERIOD_TIMEZONE) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(tz)


def resolve_period_bounds(request: PeriodRequest, now: datetime) -> PeriodBounds:
    today = now.date()
    scope = request.scope_type
    if scope == "all_workouts":
        return PeriodBounds(label="all_workouts")
    if scope == "current_week":
        start = today - timedelta(days=today.weekday())
        return _bounds(scope, start, today)
    if scope == "last_week":
        current_start = today - timedelta(days=today.weekday())
        start = current_start - timedelta(days=7)
        return _bounds(scope, start, current_start - timedelta(days=1))
    if scope == "current_month":
        return _bounds(scope, today.replace(day=1), today)
    if scope == "last_month":
        first_current = today.replace(day=1)
        previous_last = first_current - timedelta(days=1)
        return _bounds(scope, previous_last.replace(day=1), previous_last)
    if scope == "rolling_days":
        days = request.rolling_days
        if days is None or days <= 0:
            raise PeriodRequestError("rolling_days scope requires a positive rolling_days value")
        return _bounds(f"rolling_{days}_days", today - timedelta(days=days - 1), today)
    if scope == "date_range":
        start = _parse_date(request.start_date, "start_date")
        end = _parse_date(request.end_date, "end_date")
        if end < start:
            raise PeriodRequestError("date_range end_date cannot be before start_date")
        return _bounds("date_range", start, end)
    if scope == "calendar_year_to_date":
        return _bounds(scope, date(today.year, 1, 1), today)
    raise PeriodRequestError(f"Unsupported period scope: {scope}")


def aggregate_period(
    workouts: Iterable[WorkoutRecord],
    request: PeriodRequest,
    bounds: PeriodBounds,
) -> JsonObject:
    workout_list = tuple(workouts)
    metrics = _validated_metrics(request.metrics)
    grouping = request.grouping
    summary = _metric_summary(workout_list, metrics)
    facts: JsonObject = {
        "scope": {
            "type": request.scope_type,
            "value": request.scope_value,
            "label": bounds.label,
            "start_date": bounds.start_date or "",
            "end_date": bounds.end_date or "",
        },
        "filters": _safe_filters(request.filters),
        "grouping": grouping,
        "metrics": list(metrics),
        "workout_count": len(workout_list),
        "summary": summary,
        "workouts": [_compact_workout(workout, metrics) for workout in workout_list[:MAX_COMPACT_WORKOUTS]],
        "missing_data": _missing_data(workout_list, metrics),
    }
    if grouping != "none":
        facts["groups"] = _grouped_summary(workout_list, metrics, grouping)[:MAX_GROUPS_FOR_LLM]
    return facts


def _bounds(label: str, start: date, end: date) -> PeriodBounds:
    return PeriodBounds(label=label, start_date=start.isoformat(), end_date=end.isoformat())


def _parse_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PeriodRequestError(f"{field_name} must use YYYY-MM-DD") from exc


def _validated_metrics(metrics: Iterable[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(metric for metric in metrics if metric))
    if not values:
        return DEFAULT_PERIOD_METRICS
    unsupported = [metric for metric in values if metric not in PERIOD_METRICS]
    if unsupported:
        raise PeriodRequestError(f"Unsupported period metrics: {', '.join(unsupported)}")
    return values


def _safe_filters(filters: JsonObject) -> JsonObject:
    return {
        "kind": str(filters.get("kind", "") or ""),
        "primary_kind": str(filters.get("primary_kind", "") or ""),
        "tags": [str(tag) for tag in filters.get("tags", []) if str(tag)],
    }


def _metric_summary(workouts: tuple[WorkoutRecord, ...], metrics: tuple[str, ...]) -> JsonObject:
    summary: JsonObject = {}
    if "workout_count" in metrics:
        summary["workout_count"] = {"value": len(workouts)}
    for metric in metrics:
        if metric == "workout_count":
            continue
        values = [float(value) for workout in workouts if (value := getattr(workout, metric, None)) is not None]
        summary[metric] = {
            "sum": sum(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "avg": (sum(values) / len(values)) if values else None,
            "available_count": len(values),
            "missing_count": len(workouts) - len(values),
        }
    return summary


def _grouped_summary(workouts: tuple[WorkoutRecord, ...], metrics: tuple[str, ...], grouping: str) -> list[JsonObject]:
    buckets: dict[str, list[WorkoutRecord]] = {}
    for workout in workouts:
        key = _group_key(workout, grouping)
        buckets.setdefault(key, []).append(workout)
    return [
        {
            "group": key,
            "workout_count": len(group_workouts),
            "summary": _metric_summary(tuple(group_workouts), metrics),
        }
        for key, group_workouts in sorted(buckets.items())
    ]


def _group_key(workout: WorkoutRecord, grouping: str) -> str:
    workout_date = _workout_date(workout)
    if workout_date is None:
        return "unknown"
    if grouping == "day":
        return workout_date.isoformat()
    if grouping == "week":
        year, week, _ = workout_date.isocalendar()
        return f"{year}-W{week:02d}"
    if grouping == "month":
        return f"{workout_date.year:04d}-{workout_date.month:02d}"
    return "all"


def _workout_date(workout: WorkoutRecord) -> date | None:
    if workout.local_date:
        try:
            return date.fromisoformat(workout.local_date)
        except ValueError:
            return None
    return None


def _compact_workout(workout: WorkoutRecord, metrics: tuple[str, ...]) -> JsonObject:
    data: JsonObject = {
        "workout_id": workout.workout_id,
        "title": workout.title,
        "kind": workout.kind,
        "primary_kind": workout.primary_kind,
        "local_date": workout.local_date,
    }
    for metric in metrics:
        if metric != "workout_count":
            data[metric] = getattr(workout, metric, None)
    return data


def _missing_data(workouts: tuple[WorkoutRecord, ...], metrics: tuple[str, ...]) -> list[JsonObject]:
    missing = []
    for metric in metrics:
        if metric == "workout_count":
            continue
        count = sum(1 for workout in workouts if getattr(workout, metric, None) is None)
        if count:
            missing.append({"metric": metric, "missing_count": count})
    return missing
