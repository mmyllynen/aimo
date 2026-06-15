from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from storage.repositories import WorkoutRecord
from storage.unit_of_work import RepositoryBundle


class WorkoutReferenceStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class WorkoutReferenceResolution:
    status: WorkoutReferenceStatus
    workout: WorkoutRecord | None
    matches: tuple[WorkoutRecord, ...]
    selector_type: str
    selector_value: str

    @property
    def matched(self) -> bool:
        return self.status == WorkoutReferenceStatus.MATCHED and self.workout is not None


LATEST_TERMS = {"latest", "last", "viimeisin", "viimeinen", "uusin"}
ACTIVE_TERMS = {"active", "aktiivinen"}
GENERAL_TERMS = {"treeni", "treenin", "workout", "activity", "harjoitus", "harjoituksen"}
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def resolve_workout_reference(
    repositories: RepositoryBundle,
    owner_user_id: str,
    reference: str,
    *,
    default: str = "latest",
    recent_limit: int = 20,
) -> WorkoutReferenceResolution:
    raw_reference = reference.strip()
    normalized = _normalize(raw_reference)

    if not normalized:
        return _resolve_default(repositories, owner_user_id, default)
    if _matches_term(normalized, ACTIVE_TERMS):
        return _single(repositories.active_workouts.get(owner_user_id), "active", raw_reference)
    if _matches_term(normalized, LATEST_TERMS):
        return _single(repositories.workouts.latest_for_user(owner_user_id), "latest", raw_reference)

    direct = repositories.workouts.get_for_user(owner_user_id, raw_reference)
    if direct is not None:
        return _single(direct, "id", raw_reference)

    list_index = _list_index(normalized)
    if list_index is not None:
        workouts = repositories.workouts.list_for_user(owner_user_id, limit=max(recent_limit, list_index))
        if 1 <= list_index <= len(workouts):
            return _single(workouts[list_index - 1], "list_index", raw_reference)
        return _none("list_index", raw_reference)

    date_match = DATE_PATTERN.search(raw_reference)
    if date_match:
        return _from_matches(
            tuple(
                workout
                for workout in repositories.workouts.list_for_user(owner_user_id, limit=recent_limit)
                if workout.local_date == date_match.group(0)
            ),
            "date",
            date_match.group(0),
        )

    candidates = repositories.workouts.list_for_user(owner_user_id, limit=recent_limit)
    text_matches = tuple(workout for workout in candidates if _matches_workout_text(workout, normalized))
    return _from_matches(text_matches, "text", raw_reference)


def resolve_workout_selector(
    repositories: RepositoryBundle,
    owner_user_id: str,
    selector: object,
    *,
    default: str = "latest",
    recent_limit: int = 20,
) -> WorkoutReferenceResolution:
    if not isinstance(selector, dict):
        return resolve_workout_reference(repositories, owner_user_id, "", default=default, recent_limit=recent_limit)
    selector_type = _normalize(str(selector.get("type", "") or default))
    selector_value = str(selector.get("value", "") or "").strip()
    if selector_type in {"id", "workout_id", "exact"}:
        return resolve_workout_reference(
            repositories,
            owner_user_id,
            selector_value,
            default="none",
            recent_limit=recent_limit,
        )
    if selector_type in ACTIVE_TERMS:
        return resolve_workout_reference(
            repositories,
            owner_user_id,
            "active",
            default=default,
            recent_limit=recent_limit,
        )
    if selector_type in LATEST_TERMS:
        return resolve_workout_reference(
            repositories,
            owner_user_id,
            "latest",
            default=default,
            recent_limit=recent_limit,
        )
    if selector_value:
        return resolve_workout_reference(
            repositories,
            owner_user_id,
            selector_value,
            default=default,
            recent_limit=recent_limit,
        )
    return resolve_workout_reference(repositories, owner_user_id, "", default=default, recent_limit=recent_limit)


def _resolve_default(
    repositories: RepositoryBundle,
    owner_user_id: str,
    default: str,
) -> WorkoutReferenceResolution:
    if default == "active":
        return _single(repositories.active_workouts.get(owner_user_id), "active", "")
    if default == "none":
        return WorkoutReferenceResolution(
            status=WorkoutReferenceStatus.NOT_FOUND,
            workout=None,
            matches=(),
            selector_type="none",
            selector_value="",
        )
    return _single(repositories.workouts.latest_for_user(owner_user_id), "latest", "")


def _single(workout: WorkoutRecord | None, selector_type: str, selector_value: str) -> WorkoutReferenceResolution:
    if workout is None:
        return _none(selector_type, selector_value)
    return WorkoutReferenceResolution(
        status=WorkoutReferenceStatus.MATCHED,
        workout=workout,
        matches=(workout,),
        selector_type=selector_type,
        selector_value=selector_value,
    )


def _none(selector_type: str, selector_value: str) -> WorkoutReferenceResolution:
    return WorkoutReferenceResolution(
        status=WorkoutReferenceStatus.NOT_FOUND,
        workout=None,
        matches=(),
        selector_type=selector_type,
        selector_value=selector_value,
    )


def _from_matches(
    matches: tuple[WorkoutRecord, ...],
    selector_type: str,
    selector_value: str,
) -> WorkoutReferenceResolution:
    if not matches:
        return _none(selector_type, selector_value)
    if len(matches) > 1:
        return WorkoutReferenceResolution(
            status=WorkoutReferenceStatus.AMBIGUOUS,
            workout=None,
            matches=matches,
            selector_type=selector_type,
            selector_value=selector_value,
        )
    return _single(matches[0], selector_type, selector_value)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _matches_term(value: str, terms: Iterable[str]) -> bool:
    tokens = set(value.replace("#", " ").split())
    return value in terms or bool(tokens & set(terms))


def _list_index(value: str) -> int | None:
    stripped = value.removeprefix("#").strip()
    if stripped.isdecimal():
        return int(stripped)
    if stripped.startswith("nro ") and stripped[4:].isdecimal():
        return int(stripped[4:])
    if stripped.startswith("numero ") and stripped[7:].isdecimal():
        return int(stripped[7:])
    return None


def _matches_workout_text(workout: WorkoutRecord, reference: str) -> bool:
    if not reference or reference in GENERAL_TERMS:
        return False
    fields = (
        workout.title,
        workout.kind,
        workout.primary_kind,
        *(str(tag) for tag in _metadata_tags(workout)),
    )
    normalized_fields = tuple(_normalize(value) for value in fields if value)
    if any(reference == value for value in normalized_fields):
        return True
    if len(reference) < 3:
        return False
    return any(reference in value for value in normalized_fields if value)


def _metadata_tags(workout: WorkoutRecord) -> tuple[object, ...]:
    tags = workout.metadata.get("tags", ())
    if isinstance(tags, str):
        return (tags,)
    if isinstance(tags, list | tuple):
        return tuple(tags)
    return ()
