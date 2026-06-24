from __future__ import annotations

import unittest

from storage.repositories import WorkoutEstimateFeatureRecord, WorkoutRecord
from workout.route_estimate import estimate_route_time_from_features


class RouteEstimateTests(unittest.TestCase):
    def test_feature_similarity_weights_distance_and_ascent_matches(self) -> None:
        target = _workout("route", "route_plan", "route", distance_km=20.0, duration_s=None, ascent_m=200)
        target_feature = _feature("route", "route_plan", "route", distance_km=20.0, duration_s=None, ascent_m=200)
        short_fast = _feature("short-fast", "activity", "activity", distance_km=5.0, duration_s=1500, ascent_m=10)
        long_match = _feature("long-match", "activity", "activity", distance_km=20.0, duration_s=8000, ascent_m=190)
        long_match_2 = _feature("long-match-2", "activity", "activity", distance_km=18.0, duration_s=7200, ascent_m=180)

        estimate = estimate_route_time_from_features(
            target,
            target_feature,
            (),
            (short_fast, long_match, long_match_2),
            (),
        )

        self.assertIsNotNone(estimate)
        self.assertEqual(estimate.model, "feature_similarity")
        self.assertEqual(estimate.comparable_count, 3)
        self.assertGreater(estimate.baseline_pace_s_per_km, 390)
        self.assertLess(estimate.baseline_pace_s_per_km, 410)
        self.assertEqual(estimate.similarity["candidate_count"], 3)
        self.assertGreater(estimate.similarity["top_weights"][0], estimate.similarity["top_weights"][-1])

    def test_route_plan_missing_duration_is_not_user_visible_missing_data(self) -> None:
        target = _workout("route", "route_plan", "route", distance_km=20.0, duration_s=None, ascent_m=200)
        target_feature = _feature("route", "route_plan", "route", distance_km=20.0, duration_s=None, ascent_m=200)
        history = (
            _feature("long-1", "activity", "activity", distance_km=20.0, duration_s=8000, ascent_m=190),
            _feature("long-2", "activity", "activity", distance_km=18.0, duration_s=7200, ascent_m=180),
            _feature("long-3", "activity", "activity", distance_km=22.0, duration_s=9000, ascent_m=220),
        )

        estimate = estimate_route_time_from_features(target, target_feature, (), history, ())

        self.assertNotIn("quality:missing_duration", estimate.missing_data)


def _workout(
    workout_id: str,
    kind: str,
    primary_kind: str,
    *,
    distance_km: float | None,
    duration_s: float | None,
    ascent_m: float | None,
) -> WorkoutRecord:
    return WorkoutRecord(
        workout_id=workout_id,
        owner_user_id="user-1",
        source_attachment_id=None,
        guild_id="guild-1",
        channel_id="channel-1",
        title=workout_id,
        kind=kind,
        primary_kind=primary_kind,
        start_time_utc=None,
        start_time_local=None,
        local_date="2026-06-13",
        distance_km=distance_km,
        duration_s=duration_s,
        pace_s_per_km=(duration_s / distance_km) if duration_s and distance_km else None,
        ascent_m=ascent_m,
        avg_hr_bpm=None,
        max_hr_bpm=None,
        point_count=100,
        created_at="2026-06-13T10:00:00Z",
    )


def _feature(
    workout_id: str,
    kind: str,
    primary_kind: str,
    *,
    distance_km: float,
    duration_s: float | None,
    ascent_m: float,
) -> WorkoutEstimateFeatureRecord:
    ascent_per_km = ascent_m / distance_km
    return WorkoutEstimateFeatureRecord(
        workout_id=workout_id,
        owner_user_id="user-1",
        feature_version=1,
        kind=kind,
        primary_kind=primary_kind,
        local_date="2026-06-13",
        distance_km=distance_km,
        duration_s=duration_s,
        pace_s_per_km=(duration_s / distance_km) if duration_s else None,
        ascent_m=ascent_m,
        descent_m=ascent_m * 0.8,
        ascent_per_km=ascent_per_km,
        descent_per_km=ascent_per_km * 0.8,
        elevation_min_m=10,
        elevation_max_m=10 + ascent_m,
        flat_share=0.35,
        climb_share=0.35,
        steep_climb_share=0.05,
        descent_share=0.25,
        steep_descent_share=0.0,
        longest_climb_m=50,
        longest_descent_m=40,
        route_signature="",
        distance_band="10-21" if distance_km >= 10 else "5-10",
        ascent_band="rolling",
        point_count=100,
        distance_coverage=1.0,
        elevation_coverage=1.0,
        gap_count=0,
        updated_at="2026-06-13T10:00:00Z",
    )


if __name__ == "__main__":
    unittest.main()
