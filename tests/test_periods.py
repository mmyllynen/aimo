from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from llm.operations import PeriodRequest
from storage.repositories import WorkoutRecord
from workout.periods import aggregate_period, resolve_period_bounds


class PeriodTests(unittest.TestCase):
    def test_resolves_last_week_as_complete_monday_sunday_period(self) -> None:
        request = _period_request(scope_type="last_week")

        bounds = resolve_period_bounds(request, datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Helsinki")))

        self.assertEqual(bounds.start_date, "2026-06-08")
        self.assertEqual(bounds.end_date, "2026-06-14")

    def test_aggregates_all_workout_ascent_without_raw_points(self) -> None:
        request = _period_request(scope_type="all_workouts", metrics=("ascent_m",))

        facts = aggregate_period(
            (
                _workout("workout-1", "2026-06-01", ascent_m=20),
                _workout("workout-2", "2026-06-02", ascent_m=30),
            ),
            request,
            resolve_period_bounds(request, datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Helsinki"))),
        )

        self.assertEqual(facts["workout_count"], 2)
        self.assertEqual(facts["summary"]["ascent_m"]["sum"], 50)
        self.assertNotIn("workout_points", facts)
        self.assertEqual(facts["workouts"][0]["ascent_m"], 20)

    def test_groups_period_by_week(self) -> None:
        request = _period_request(scope_type="current_month", metrics=("distance_km",), grouping="week")

        facts = aggregate_period(
            (
                _workout("workout-1", "2026-06-01", distance_km=5),
                _workout("workout-2", "2026-06-08", distance_km=7),
            ),
            request,
            resolve_period_bounds(request, datetime(2026, 6, 16, 12, 0, tzinfo=ZoneInfo("Europe/Helsinki"))),
        )

        self.assertEqual([group["group"] for group in facts["groups"]], ["2026-W23", "2026-W24"])
        self.assertEqual(facts["groups"][0]["summary"]["distance_km"]["sum"], 5)
        self.assertEqual(facts["groups"][1]["summary"]["distance_km"]["sum"], 7)


def _period_request(
    *,
    scope_type: str,
    metrics: tuple[str, ...] = ("workout_count", "distance_km", "duration_s", "ascent_m"),
    grouping: str = "none",
) -> PeriodRequest:
    return PeriodRequest(
        scope_type=scope_type,
        scope_value="",
        start_date="",
        end_date="",
        rolling_days=None,
        filters={},
        metrics=metrics,
        grouping=grouping,
        output_mode="prose",
        comparison_mode="none",
    )


def _workout(
    workout_id: str,
    local_date: str,
    *,
    distance_km: float | None = None,
    duration_s: float | None = None,
    ascent_m: float | None = None,
) -> WorkoutRecord:
    return WorkoutRecord(
        workout_id=workout_id,
        owner_user_id="user-1",
        source_attachment_id=None,
        guild_id="guild-1",
        channel_id="channel-1",
        title=workout_id,
        kind="activity",
        primary_kind="activity",
        start_time_utc=f"{local_date}T07:00:00Z",
        start_time_local=f"{local_date}T10:00:00+03:00",
        local_date=local_date,
        distance_km=distance_km,
        duration_s=duration_s,
        pace_s_per_km=None,
        ascent_m=ascent_m,
        avg_hr_bpm=None,
        max_hr_bpm=None,
        point_count=0,
        created_at=f"{local_date}T10:30:00Z",
    )


if __name__ == "__main__":
    unittest.main()
