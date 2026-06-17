from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from core.errors import AppError, ErrorCategory
from core.events import CanonicalEvent, EventKind
from core.i18n import TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingComponent, OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from storage.repositories import PendingWorkoutDeleteRecord
from storage.repositories import HeartRateZoneRecord, WorkoutRecord
from storage.unit_of_work import RepositoryBundle
from workout.references import WorkoutReferenceResolution, WorkoutReferenceStatus, resolve_workout_reference


SUPPORTED_ACTIONS = {
    "listaa",
    "nayta",
    "aktiivinen",
    "aseta_aktiivinen",
    "poista",
    "nimea",
    "tagaa",
    "poista_tagi",
    "sykerajat",
    "aseta_sykerajat",
}
DELETE_CONFIRM_COMPONENT = "workout_delete_confirm"
DELETE_CANCEL_COMPONENT = "workout_delete_cancel"

HR_ZONE_KEYS = ("z1", "z2", "z3", "z4", "z5")
HR_ZONE_LABELS = ("pk1", "pk2", "vk1", "vk2", "mk")
HR_MAX_ZONE_MULTIPLIERS = (0.60, 0.70, 0.80, 0.90, 1.00)
DELETE_CONFIRMATION_TTL_SECONDS = 60


@dataclass(frozen=True)
class WorkoutManagementWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
    ) -> WorkflowResult:
        options = _options(event)
        action = _action(event)
        if event.kind == EventKind.COMPONENT:
            if action == DELETE_CONFIRM_COMPONENT:
                return self._confirm_delete(event, repositories)
            if action == DELETE_CANCEL_COMPONENT:
                return self._cancel_delete(event, repositories)
            return _user_error(TranslationKey.ERROR_UNEXPECTED, ErrorCategory.UNEXPECTED)

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
        if action == "nimea":
            return self._rename(event, repositories, str(options.get("viite", "")).strip(), str(options.get("nimi", "")).strip())
        if action == "tagaa":
            return self._add_tag(event, repositories, str(options.get("viite", "")).strip(), str(options.get("tagi", "")).strip())
        if action == "poista_tagi":
            return self._remove_tag(event, repositories, str(options.get("viite", "")).strip(), str(options.get("tagi", "")).strip())
        if action == "sykerajat":
            return self._list_hr_zones(event, repositories)
        if action == "aseta_sykerajat":
            return self._set_hr_zones(event, repositories, options.get("zones"))
        return _user_error(TranslationKey.ERROR_UNEXPECTED, ErrorCategory.UNEXPECTED)

    def _list(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        workouts = repositories.workouts.list_for_user(event.user_id)
        if not workouts:
            return _message(TranslationKey.WORKOUT_LIST_EMPTY)
        active = repositories.active_workouts.get(event.user_id)
        active_id = active.workout_id if active is not None else ""
        items = "\n".join(_workout_line(index, workout, active_id=active_id) for index, workout in enumerate(workouts, start=1))
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
        _set_current_workout(event, repositories, resolved.workout)
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
        _set_current_workout(event, repositories, workout)
        return _message(TranslationKey.WORKOUT_ACTIVE_SET, title=workout.title)

    def _delete(
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
        pending_id = f"{event.event_id}:pending-delete"
        expires_at = _timestamp_after(event.created_at, DELETE_CONFIRMATION_TTL_SECONDS)
        repositories.pending_workout_deletes.create(
            PendingWorkoutDeleteRecord(
                pending_id=pending_id,
                user_id=event.user_id,
                guild_id=event.guild_id,
                channel_id=event.channel_id,
                workout_id=workout.workout_id,
                token="button",
                created_at=_timestamp(event.created_at),
                expires_at=expires_at,
                source_event_id=event.event_id,
                metadata={"title": workout.title},
            )
        )
        return _message(
            TranslationKey.WORKOUT_DELETE_PENDING,
            title=workout.title or workout.workout_id,
            reference=workout_id or workout.workout_id,
            components=(
                OutgoingComponent(
                    component_id=_delete_component_id(DELETE_CONFIRM_COMPONENT, pending_id),
                    label="Poista",
                    style="danger",
                ),
                OutgoingComponent(
                    component_id=_delete_component_id(DELETE_CANCEL_COMPONENT, pending_id),
                    label="Peruuta",
                    style="secondary",
                ),
            ),
        )

    def _confirm_delete(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        pending = _pending_delete(event, repositories)
        if pending is None:
            return _user_error(TranslationKey.WORKOUT_DELETE_CONFIRMATION_INVALID, ErrorCategory.PERMISSION_DENIED)
        if _timestamp(event.created_at) > pending.expires_at:
            repositories.pending_workout_deletes.clear_for_user(event.user_id)
            return _user_error(TranslationKey.WORKOUT_DELETE_CONFIRMATION_EXPIRED, ErrorCategory.PERMISSION_DENIED)
        workout = repositories.workouts.get_for_user(event.user_id, pending.workout_id)
        if workout is None:
            repositories.pending_workout_deletes.clear_for_user(event.user_id)
            return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)
        repositories.workouts.delete_for_user(event.user_id, workout.workout_id)
        repositories.pending_workout_deletes.clear_for_user(event.user_id)
        return _message(TranslationKey.WORKOUT_DELETED, title=workout.title)

    def _cancel_delete(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        pending = _pending_delete(event, repositories)
        if pending is None:
            return _user_error(TranslationKey.WORKOUT_DELETE_CONFIRMATION_INVALID, ErrorCategory.PERMISSION_DENIED)
        repositories.pending_workout_deletes.clear_for_user(event.user_id)
        return _message(TranslationKey.WORKOUT_DELETE_CANCELLED)

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

    def _rename(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        workout_id: str,
        title: str,
    ) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        title = _clean_title(title)
        if not title:
            return _user_error(TranslationKey.ERROR_UNEXPECTED, ErrorCategory.UNEXPECTED)
        assert resolved.workout is not None
        repositories.workouts.rename_for_user(event.user_id, resolved.workout.workout_id, title)
        updated = repositories.workouts.get_for_user(event.user_id, resolved.workout.workout_id) or resolved.workout
        _set_current_workout(event, repositories, updated)
        return _message(TranslationKey.WORKOUT_RENAMED, title=title)

    def _add_tag(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        workout_id: str,
        tag: str,
    ) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        tag = _clean_tag(tag)
        if not tag:
            return _user_error(TranslationKey.WORKOUT_TAG_INVALID, ErrorCategory.UNEXPECTED)
        assert resolved.workout is not None
        repositories.workouts.add_tag_for_user(event.user_id, resolved.workout.workout_id, tag)
        _set_current_workout(event, repositories, resolved.workout)
        return _message(TranslationKey.WORKOUT_TAG_ADDED, title=resolved.workout.title, tag=tag)

    def _remove_tag(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        workout_id: str,
        tag: str,
    ) -> WorkflowResult:
        resolved = resolve_workout_reference(repositories, event.user_id, workout_id, default="latest")
        if error := _reference_error(resolved):
            return error
        tag = _clean_tag(tag)
        if not tag:
            return _user_error(TranslationKey.WORKOUT_TAG_INVALID, ErrorCategory.UNEXPECTED)
        assert resolved.workout is not None
        removed = repositories.workouts.remove_tag_for_user(event.user_id, resolved.workout.workout_id, tag)
        if not removed:
            return _user_error(TranslationKey.ERROR_NO_MATCHING_WORKOUT, ErrorCategory.NO_MATCHING_WORKOUT)
        _set_current_workout(event, repositories, resolved.workout)
        return _message(TranslationKey.WORKOUT_TAG_REMOVED, title=resolved.workout.title, tag=tag)


def _options(event: CanonicalEvent) -> dict[str, Any]:
    options = event.metadata.get("options", {})
    if isinstance(options, dict):
        return options
    return {}


def _action(event: CanonicalEvent) -> str:
    return str(event.metadata.get("subcommand", "")).strip().lower()


def _pending_delete(event: CanonicalEvent, repositories: RepositoryBundle) -> PendingWorkoutDeleteRecord | None:
    pending_id = str(event.metadata.get("pending_id", "")).strip()
    if not pending_id:
        return None
    return repositories.pending_workout_deletes.get_for_user(event.user_id, pending_id)


def _delete_component_id(action: str, pending_id: str) -> str:
    return f"treenit:{action}:{pending_id}"


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


def _clean_title(value: str) -> str:
    return " ".join(value.split())[:120]


def _clean_tag(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-")
    if not normalized or len(normalized) > 40:
        return ""
    if not all(character.isalnum() or character in {"-", "_"} for character in normalized):
        return ""
    return normalized


def _message(
    key: TranslationKey,
    *,
    components: tuple[OutgoingComponent, ...] = (),
    **params: Any,
) -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.SUCCESS,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.EPHEMERAL_TEXT,
                text_key=key.value,
                text_params=params,
                components=components,
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
    tags = ""
    return _message(
        TranslationKey.WORKOUT_DETAILS,
        title=workout.title or workout.workout_id,
        date=_format_datetime(workout.start_time_local, workout.local_date),
        kind=_format_kind(workout.primary_kind or workout.kind) or "-",
        distance_km=_format_number(workout.distance_km),
        duration=_format_duration(workout.duration_s),
        avg_hr=_format_heart_rate(workout.avg_hr_bpm),
        ascent=_format_ascent(workout.ascent_m),
        tags=tags,
    )


def _set_current_workout(event: CanonicalEvent, repositories: RepositoryBundle, workout: WorkoutRecord) -> None:
    repositories.active_workouts.set(
        user_id=event.user_id,
        workout_id=workout.workout_id,
        updated_at=event.created_at,
    )


def _workout_line(index: int, workout: WorkoutRecord, *, active_id: str = "") -> str:
    title = workout.title or "Nimetön treeni"
    date = _format_datetime(workout.start_time_local, workout.local_date)
    metrics = ", ".join(_workout_metric_parts(workout))
    marker = " *" if workout.workout_id == active_id else ""
    if metrics:
        return f"{index}. {date} - {title}{marker}\n   {metrics}"
    return f"{index}. {date} - {title}{marker}"


def _workout_metric_parts(workout: WorkoutRecord) -> tuple[str, ...]:
    parts = [_format_kind(workout.primary_kind or workout.kind)]
    if workout.distance_km is not None:
        parts.append(f"{_format_decimal(workout.distance_km, digits=1)} km")
    if workout.duration_s is not None:
        parts.append(_format_duration(workout.duration_s))
    if workout.avg_hr_bpm is not None:
        parts.append(f"keskisyke {int(round(workout.avg_hr_bpm))}")
    if workout.ascent_m is not None:
        parts.append(f"nousu {int(round(workout.ascent_m))} m")
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


def _format_datetime(start_time_local: str | None, local_date: str | None) -> str:
    date = _format_date(local_date)
    if not start_time_local or "T" not in start_time_local:
        return date
    time_part = start_time_local.split("T", 1)[1][:5]
    if not time_part or ":" not in time_part:
        return date
    return f"{date} {time_part}"


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


def _format_heart_rate(value: float | None) -> str:
    if value is None:
        return "-"
    return str(int(round(value)))


def _format_ascent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{int(round(value))} m"


def _timestamp_after(value: datetime | str, seconds: int) -> str:
    return _format_timestamp(_parse_timestamp(value) + timedelta(seconds=seconds))


def _timestamp(value: datetime | str) -> str:
    return _format_timestamp(_parse_timestamp(value))


def _parse_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
