from __future__ import annotations

import unittest

from storage.repositories import WorkoutRecord
from storage.unit_of_work import UnitOfWork, open_database
from workout.references import WorkoutReferenceStatus, resolve_workout_reference


class WorkoutReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self._seed_workouts()

    def tearDown(self) -> None:
        self.connection.close()

    def test_empty_reference_defaults_to_latest(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            resolved = resolve_workout_reference(repositories, "user-1", "")

        self.assertEqual(resolved.status, WorkoutReferenceStatus.MATCHED)
        self.assertEqual(resolved.workout.workout_id, "workout-3")
        self.assertEqual(resolved.selector_type, "latest")

    def test_list_index_matches_current_list_order(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            resolved = resolve_workout_reference(repositories, "user-1", "#2", default="none")

        self.assertEqual(resolved.status, WorkoutReferenceStatus.MATCHED)
        self.assertEqual(resolved.workout.workout_id, "workout-2")
        self.assertEqual(resolved.selector_type, "list_index")

    def test_date_reference_is_ambiguous_when_multiple_workouts_share_day(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            resolved = resolve_workout_reference(repositories, "user-1", "2026-06-13", default="none")

        self.assertEqual(resolved.status, WorkoutReferenceStatus.AMBIGUOUS)
        self.assertEqual([workout.workout_id for workout in resolved.matches], ["workout-3", "workout-2"])

    def test_date_reference_matches_unique_day(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            resolved = resolve_workout_reference(repositories, "user-1", "2026-06-12", default="none")

        self.assertEqual(resolved.status, WorkoutReferenceStatus.MATCHED)
        self.assertEqual(resolved.workout.workout_id, "workout-1")

    def test_text_reference_matches_title_kind_or_metadata_tag(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            title = resolve_workout_reference(repositories, "user-1", "easy jog", default="none")
            kind = resolve_workout_reference(repositories, "user-1", "cycling", default="none")
            tag = resolve_workout_reference(repositories, "user-1", "interval", default="none")

        self.assertEqual(title.workout.workout_id, "workout-1")
        self.assertEqual(kind.workout.workout_id, "workout-3")
        self.assertEqual(tag.workout.workout_id, "workout-2")

    def test_text_reference_can_be_ambiguous(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            resolved = resolve_workout_reference(repositories, "user-1", "run", default="none")

        self.assertEqual(resolved.status, WorkoutReferenceStatus.AMBIGUOUS)
        self.assertEqual([workout.workout_id for workout in resolved.matches], ["workout-2", "workout-1"])

    def _seed_workouts(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            for workout in (
                _workout(
                    "workout-1",
                    title="Easy jog",
                    kind="run",
                    start_time="2026-06-12T08:00:00+03:00",
                    local_date="2026-06-12",
                    created_at="2026-06-12T06:00:00Z",
                ),
                _workout(
                    "workout-2",
                    title="Morning run",
                    kind="run",
                    start_time="2026-06-13T08:00:00+03:00",
                    local_date="2026-06-13",
                    created_at="2026-06-13T06:00:00Z",
                    metadata={"tags": ["interval"]},
                ),
                _workout(
                    "workout-3",
                    title="Lunch ride",
                    kind="cycling",
                    start_time="2026-06-13T12:00:00+03:00",
                    local_date="2026-06-13",
                    created_at="2026-06-13T10:00:00Z",
                ),
            ):
                repositories.workouts.add(workout)


def _workout(
    workout_id: str,
    *,
    title: str,
    kind: str,
    start_time: str,
    local_date: str,
    created_at: str,
    metadata: dict[str, object] | None = None,
) -> WorkoutRecord:
    return WorkoutRecord(
        workout_id=workout_id,
        owner_user_id="user-1",
        source_attachment_id=None,
        guild_id="guild-1",
        channel_id="channel-1",
        title=title,
        kind=kind,
        primary_kind=kind,
        start_time_utc=None,
        start_time_local=start_time,
        local_date=local_date,
        distance_km=5.0,
        duration_s=1800,
        pace_s_per_km=360,
        ascent_m=20,
        avg_hr_bpm=130,
        max_hr_bpm=150,
        point_count=0,
        created_at=created_at,
        metadata=metadata or {},
    )


if __name__ == "__main__":
    unittest.main()
