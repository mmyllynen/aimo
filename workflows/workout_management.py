from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.errors import AppError, ErrorCategory
from core.events import CanonicalEvent
from core.i18n import TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from storage.repositories import HeartRateZoneRecord, WorkoutRecord
from storage.unit_of_work import RepositoryBundle
from workout.references import WorkoutReferenceResolution, WorkoutReferenceStatus, resolve_workout_reference


SUPPORTED_ACTIONS = {
    "listaa",
    "nayta",
    "aktiivinen",
    "aseta_aktiivinen",
    "poista",
    "sykerajat",
    "aseta_sykerajat",
}

HR_ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")
HR_ZONE_LABELS = ("pk1", "pk2", "vk1", "vk2", "mk")
HR_MAX_ZONE_MULTIPLIERS = (0.60, 0.70, 0.80, 0.90, 1.00)


@dataclass(frozen=True)
class WorkoutManagementWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
    ) -> WorkflowResult:
        options = _options(event)
        action = str(options.get("toiminto") or event.text).strip().lower()
        if action not in SUPPORTED_ACTIONS:
            action = "listaa"

        if action == "listaa":
            return self._list(event, repositories)
        if action == "nayta":
            return self._show(event, repositories, str(options.get("viite", "")).strip())
        if action == "aktiivinen":
            return self._active(event, repositories)
        if action == "aseta_aktiivinen":
            return self._set_active(event, repositories, str(options.get("viite", "")).strip())
        if action == "poista":
            return self._delete(event, repositories, str(options.get("viite", "")).strip())
        if action == "sykerajat":
            return self._list_hr_zones(event, repositories)
        if action == "aseta_sykerajat":
            return self._set_hr_zones(event, repositories, options.get("zones"))
        return _user_error(TranslationKey.ERROR_UNEXPECTED, ErrorCategory.UNEXPECTED)

    def _list(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        workouts = repositories.workouts.list_for_user(event.user_id)
        if not workouts:
            return _message(TranslationKey.WORKOUT_LIST_EMPTY)
        items = "\n".join(_workout_line(index, workout) for index, workout in enumerate(workouts, start=1))
        items = f"{items}\n\nVoit viitata treeniin numerolla, päivämäärällä tai nimellä."
        return _message(
            TranslationKey.WORKOUT_LIST_SUMMARY,
            count=_workout_count_text(len(workouts)),
            items=items,
        )

    def _show(self, event: CanonicalEvent, repositories: RepositoryBundle, workout_id: str) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        assert resolved.workout is not None
        return _workout_details(resolved.workout)

    def _active(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        workout = repositories.active_workouts.get(event.user_id)
        if workout is None:
            return _message(TranslationKey.WORKOUT_ACTIVE_EMPTY)
        return _workout_details(workout)

    def _set_active(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        workout_id: str,
    ) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        assert resolved.workout is not None
        workout = resolved.workout
        repositories.active_workouts.set(
            user_id=event.user_id,
            workout_id=workout.workout_id,
            updated_at=event.created_at,
        )
        return _message(TranslationKey.WORKOUT_ACTIVE_SET, title=workout.title)

    def _delete(self, event: CanonicalEvent, repositories: RepositoryBundle, workout_id: str) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        assert resolved.workout is not None
        workout = resolved.workout
        repositories.workouts.delete_for_user(event.user_id, workout.workout_id)
        return _message(TranslationKey.WORKOUT_DELETED, title=workout.title)

    def _list_hr_zones(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        zones = repositories.heart_rate_zones.list_for_user(event.user_id)
        if not zones:
            return _message(TranslationKey.HR_ZONES_EMPTY)
        return _message(
            TranslationKey.HR_ZONES_SUMMARY,
            zones="\n".join(_zone_line(zone) for zone in zones),
        )

    def _set_hr_zones(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        zones_payload: Any,
    ) -> WorkflowResult:
        upper_limits = _parse_zone_upper_limits(zones_payload)
        if upper_limits is None:
            return _user_error(TranslationKey.HR_ZONES_INVALID, ErrorCategory.UNEXPECTED)
        if not upper_limits:
            return _message(TranslationKey.HR_ZONES_EMPTY)
        zones = _zones_from_upper_limits(event.user_id, upper_limits)
        repositories.heart_rate_zones.replace_for_user(event.user_id, zones)
        return _message(TranslationKey.HR_ZONES_UPDATED)


def _options(event: CanonicalEvent) -> dict[str, Any]:
    options = event.metadata.get("options", {})
    if isinstance(options, dict):
        return options
    return {}


def _parse_zone_upper_limits(payload: Any) -> tuple[int, ...] | None:
    if payload is None:
        return ()
    if isinstance(payload, str) and not payload.strip():
        return ()
    values = _parse_integer_values(payload)
    if values is None:
        return None
    if len(values) == 1:
        max_hr = values[0]
        if max_hr <= 0:
            return None
        return tuple(int(round(max_hr * multiplier)) for multiplier in HR_MAX_ZONE_MULTIPLIERS)
    if len(values) == len(HR_ZONE_KEYS) and _strictly_increasing(values):
        return values
    return None


def _parse_integer_values(payload: Any) -> tuple[int, ...] | None:
    if isinstance(payload, int):
        return (payload,)
    if not isinstance(payload, str):
        return None
    normalized = payload.replace(";", ",")
    parts = tuple(part.strip() for part in normalized.split(",") if part.strip())
    if not parts:
        return ()
    if not all(part.isdecimal() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _strictly_increasing(values: tuple[int, ...]) -> bool:
    return all(current > previous for previous, current in zip(values, values[1:]))


def _message(key: TranslationKey, **params: Any) -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.SUCCESS,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.EPHEMERAL_TEXT,
                text_key=key.value,
                text_params=params,
            ),
        ),
    )


def _user_error(key: TranslationKey, category: ErrorCategory) -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.USER_ERROR,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.EPHEMERAL_TEXT,
                text_key=key.value,
            ),
        ),
        error=AppError(
            category=category,
            message=key.value,
            user_message_key=key.value,
        ),
    )


def _reference_error(resolved: WorkoutReferenceResolution) -> WorkflowResult | None:
    if resolved.status == WorkoutReferenceStatus.MATCHED:
        return None
    if resolved.status == WorkoutReferenceStatus.AMBIGUOUS:
        return _user_error(TranslationKey.ERROR_AMBIGUOUS_WORKOUT, ErrorCategory.AMBIGUOUS_WORKOUT)
    return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)


def _workout_details(workout: WorkoutRecord) -> WorkflowResult:
    return _message(
        TranslationKey.WORKOUT_DETAILS,
        title=workout.title or workout.workout_id,
        date=workout.local_date or "",
        distance_km=_format_number(workout.distance_km),
        duration=_format_duration(workout.duration_s),
    )


def _workout_line(index: int, workout: WorkoutRecord) -> str:
    title = workout.title or "Nimetön treeni"
    date = _format_date(workout.local_date)
    metrics = ", ".join(_workout_metric_parts(workout))
    if metrics:
        return f"{index}. {date} - {title}\n   {metrics}"
    return f"{index}. {date} - {title}"


def _workout_metric_parts(workout: WorkoutRecord) -> tuple[str, ...]:
    parts = [_format_kind(workout.primary_kind or workout.kind)]
    if workout.distance_km is not None:
        parts.append(f"{_format_decimal(workout.distance_km, digits=1)} km")
    if workout.duration_s is not None:
        parts.append(_format_duration(workout.duration_s))
    if workout.avg_hr_bpm is not None:
        parts.append(f"keskisyke {int(round(workout.avg_hr_bpm))}")
    return tuple(part for part in parts if part)


def _workout_count_text(count: int) -> str:
    if count == 1:
        return "1 treenin"
    return f"{count} treeniä"


def _format_date(value: str | None) -> str:
    if not value:
        return "ei päivää"
    parts = value.split("-")
    if len(parts) == 3 and all(part.isdecimal() for part in parts):
        year, month, day = parts
        return f"{int(day)}.{int(month)}.{year}"
    return value


def _format_kind(value: str) -> str:
    normalized = value.strip().lower()
    labels = {
        "run": "Juoksu",
        "running": "Juoksu",
        "ride": "Pyöräily",
        "cycling": "Pyöräily",
        "bike": "Pyöräily",
        "walk": "Kävely",
        "walking": "Kävely",
        "hike": "Vaellus",
        "hiking": "Vaellus",
        "activity": "Treeni",
        "route": "Reitti",
    }
    return labels.get(normalized, value or "Treeni")


def _zone_line(zone: HeartRateZoneRecord) -> str:
    lower = "" if zone.lower_bpm is None else str(zone.lower_bpm)
    upper = "" if zone.upper_bpm is None else str(zone.upper_bpm)
    return f"- {zone.label}: {lower}-{upper} bpm"


def _zones_from_upper_limits(user_id: str, upper_limits: tuple[int, ...]) -> tuple[HeartRateZoneRecord, ...]:
    zones = []
    lower_bpm: int | None = None
    for index, upper_bpm in enumerate(upper_limits):
        zones.append(
            HeartRateZoneRecord(
                user_id=user_id,
                zone_key=HR_ZONE_KEYS[index],
                label=HR_ZONE_LABELS[index],
                lower_bpm=lower_bpm,
                upper_bpm=upper_bpm,
                sort_order=index + 1,
            )
        )
        lower_bpm = upper_bpm + 1
    return tuple(zones)


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    return _format_decimal(value, digits=2)


def _format_decimal(value: float, *, digits: int) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _format_duration(value: float | None) -> str:
    if value is None:
        return "-"
    seconds = int(value)
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"
