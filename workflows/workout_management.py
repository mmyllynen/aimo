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


SUPPORTED_ACTIONS = {
    "listaa",
    "nayta",
    "aktiivinen",
    "aseta_aktiivinen",
    "poista",
    "sykerajat",
    "aseta_sykerajat",
}


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
        items = "\n".join(_workout_line(workout) for workout in workouts)
        return _message(
            TranslationKey.WORKOUT_LIST_SUMMARY,
            count=len(workouts),
            items=items,
        )

    def _show(self, event: CanonicalEvent, repositories: RepositoryBundle, workout_id: str) -> WorkflowResult:
        workout = repositories.workouts.get_for_user(event.user_id, workout_id)
        if workout is None:
            return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)
        return _workout_details(workout)

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
        workout = repositories.workouts.get_for_user(event.user_id, workout_id)
        if workout is None:
            return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)
        repositories.active_workouts.set(
            user_id=event.user_id,
            workout_id=workout.workout_id,
            updated_at=event.created_at,
        )
        return _message(TranslationKey.WORKOUT_ACTIVE_SET, title=workout.title)

    def _delete(self, event: CanonicalEvent, repositories: RepositoryBundle, workout_id: str) -> WorkflowResult:
        workout = repositories.workouts.get_for_user(event.user_id, workout_id)
        if workout is None:
            return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)
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
        zones = tuple(_zone_from_payload(event.user_id, index, zone) for index, zone in enumerate(zones_payload or ()))
        if not zones:
            return _message(TranslationKey.HR_ZONES_EMPTY)
        repositories.heart_rate_zones.replace_for_user(event.user_id, zones)
        return _message(TranslationKey.HR_ZONES_UPDATED)


def _options(event: CanonicalEvent) -> dict[str, Any]:
    options = event.metadata.get("options", {})
    if isinstance(options, dict):
        return options
    return {}


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


def _workout_details(workout: WorkoutRecord) -> WorkflowResult:
    return _message(
        TranslationKey.WORKOUT_DETAILS,
        title=workout.title or workout.workout_id,
        date=workout.local_date or "",
        distance_km=_format_number(workout.distance_km),
        duration=_format_duration(workout.duration_s),
    )


def _workout_line(workout: WorkoutRecord) -> str:
    return f"- {workout.workout_id}: {workout.title or '(untitled)'} ({workout.local_date or 'no date'})"


def _zone_line(zone: HeartRateZoneRecord) -> str:
    lower = "" if zone.lower_bpm is None else str(zone.lower_bpm)
    upper = "" if zone.upper_bpm is None else str(zone.upper_bpm)
    return f"- {zone.label}: {lower}-{upper} bpm"


def _zone_from_payload(user_id: str, index: int, payload: Any) -> HeartRateZoneRecord:
    if not isinstance(payload, dict):
        raise ValueError("HR zone payload must be a mapping")
    return HeartRateZoneRecord(
        user_id=user_id,
        zone_key=str(payload.get("zone_key") or f"z{index + 1}"),
        label=str(payload.get("label") or f"Zone {index + 1}"),
        lower_bpm=payload.get("lower_bpm"),
        upper_bpm=payload.get("upper_bpm"),
        sort_order=int(payload.get("sort_order", index + 1)),
    )


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _format_duration(value: float | None) -> str:
    if value is None:
        return "-"
    seconds = int(value)
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{remainder:02d}"
    return f"{minutes}:{remainder:02d}"
