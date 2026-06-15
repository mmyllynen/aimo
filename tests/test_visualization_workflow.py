from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.dispatcher import DispatchContext, Dispatcher, route_event
from core.events import CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.routing import WorkflowTarget
from core.workflows import OutgoingKind, WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from storage.unit_of_work import UnitOfWork, open_database


class VisualizationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_latest_workout_visualization_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True)

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(result.messages[0].content), 1000)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.VISUALIZATION_CREATED)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_bpm",))

    def test_latest_workout_visualization_writes_artifact_when_root_is_configured(self) -> None:
        self._seed_workout(with_heart_rate=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.dispatcher.dispatch(
                _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
                DispatchContext(UnitOfWork(self.connection), artifact_path=Path(tmpdir)),
            )

            self.assertEqual(result.status, WorkflowStatus.SUCCESS)
            with UnitOfWork(self.connection) as repositories:
                artifacts = repositories.rendered_artifacts.list_for_user("user-1")
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(Path(artifacts[0].storage_path).read_bytes(), result.messages[0].content)
            self.assertEqual(artifacts[0].metadata["storage_status"], "written")

    def test_latest_workout_visualization_scales_secondary_series(self) -> None:
        self._seed_workout(with_heart_rate=True)

        result = self.dispatcher.dispatch(
            _mention(
                "event-1",
                "piirrä viimeisimmästä treenistä syke ajan funktiona, piirrä samaan kuvaajaan myös vauhti ja maaston korkeuskäyrät skaalattuna samalle alueelle",
            ),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(
            result.messages[0].metadata["rendered_metrics"],
            ("heart_rate_bpm", "pace_s_per_km", "elevation_m"),
        )
        self.assertEqual(result.messages[0].metadata["scaled_metrics"], ("pace_s_per_km", "elevation_m"))

    def test_latest_workout_hr_zone_distribution_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=True)

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin sykealuejakauma"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.messages[0].filename, "workout-1-hr-zone-distribution.png")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))

    def test_latest_workout_hr_zone_distribution_requires_configured_zones(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=False)

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin sykealuejakauma"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "missing_metric")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.HR_ZONES_EMPTY)

    def test_latest_workout_missing_primary_metric_returns_specific_error_without_clarification(self) -> None:
        self._seed_workout(with_heart_rate=False)

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "missing_metric")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_MISSING_METRIC)
        self.assertEqual(result.messages[0].localized_text.params["metric"], "heart_rate_bpm")

    def test_visualization_intent_llm_input_does_not_include_workout_points(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = FakeLLMClient(
            {
                LLMOperation.VISUALIZATION_INTENT: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["heart_rate_bpm"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                }
            }
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "draw latest heart rate chart"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.EN,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        visualization_request = next(
            request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT
        )
        self.assertNotIn("workout_points", visualization_request.user_payload)
        self.assertNotIn("raw_points", visualization_request.user_payload)

    def test_invalid_render_plan_returns_user_error(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = FakeLLMClient(
            {
                LLMOperation.VISUALIZATION_INTENT: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["invented_metric"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                }
            }
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "draw latest heart rate chart"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "visualization_plan_invalid")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID)

    def test_route_event_marks_chart_language_as_visualization(self) -> None:
        route = route_event(_mention("event-1", "piirrä kuvaaja viimeisimmästä treenistä"))

        self.assertEqual(route.target, WorkflowTarget.VISUALIZATION)

    def test_comparison_visualization_uses_recent_owned_workouts(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="Older run",
            distance_km=5.0,
            created_at="2026-06-12T10:30:00Z",
            start_time_local="2026-06-12T10:00:00+03:00",
            local_date="2026-06-12",
            with_heart_rate=True,
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Newer run",
            distance_km=7.0,
            created_at="2026-06-13T10:30:00Z",
            start_time_local="2026-06-13T10:00:00+03:00",
            local_date="2026-06-13",
            with_heart_rate=True,
        )
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            repositories.workouts.add(
                WorkoutRecord(
                    workout_id="other-user-workout",
                    owner_user_id="user-2",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Other user run",
                    kind="activity",
                    primary_kind="activity",
                    start_time_utc="2026-06-14T07:00:00Z",
                    start_time_local="2026-06-14T10:00:00+03:00",
                    local_date="2026-06-14",
                    distance_km=99.0,
                    duration_s=600,
                    pace_s_per_km=600,
                    ascent_m=10,
                    avg_hr_bpm=130,
                    max_hr_bpm=140,
                    point_count=0,
                    created_at="2026-06-14T10:30:00Z",
                )
            )

        result = self.dispatcher.dispatch(
            _mention("event-1", "vertaa kahta viimeisintä treeniä matkan perusteella"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("distance_km",))
        self.assertEqual(result.messages[0].metadata["workout_id"], "workout-2")

    def _seed_workout(
        self,
        *,
        with_heart_rate: bool,
        with_zones: bool = False,
        workout_id: str = "workout-1",
        title: str = "Morning run",
        distance_km: float = 1.0,
        created_at: str = "2026-06-13T10:30:00Z",
        start_time_local: str = "2026-06-13T10:00:00+03:00",
        local_date: str = "2026-06-13",
    ) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            if with_zones:
                repositories.heart_rate_zones.replace_for_user(
                    "user-1",
                    (
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z1",
                            label="Easy",
                            upper_bpm=124,
                            sort_order=1,
                        ),
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z2",
                            label="Steady",
                            lower_bpm=125,
                            upper_bpm=134,
                            sort_order=2,
                        ),
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z3",
                            label="Hard",
                            lower_bpm=135,
                            sort_order=3,
                        ),
                    ),
                )
            workout = WorkoutRecord(
                workout_id=workout_id,
                owner_user_id="user-1",
                source_attachment_id=None,
                guild_id="guild-1",
                channel_id="channel-1",
                title=title,
                kind="activity",
                primary_kind="activity",
                start_time_utc=start_time_local,
                start_time_local=start_time_local,
                local_date=local_date,
                distance_km=distance_km,
                duration_s=600,
                pace_s_per_km=600,
                ascent_m=10,
                avg_hr_bpm=130 if with_heart_rate else None,
                max_hr_bpm=140 if with_heart_rate else None,
                point_count=3,
                created_at=created_at,
            )
            repositories.workouts.add(workout)
            repositories.workout_streams.replace_for_workout(
                workout.workout_id,
                points=(
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=0,
                        elapsed_s=0,
                        distance_km=0,
                        elevation_m=10,
                        heart_rate_bpm=120 if with_heart_rate else None,
                        pace_s_per_km=620,
                    ),
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=1,
                        elapsed_s=300,
                        distance_km=0.5,
                        elevation_m=15,
                        heart_rate_bpm=130 if with_heart_rate else None,
                        pace_s_per_km=600,
                    ),
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=2,
                        elapsed_s=600,
                        distance_km=1.0,
                        elevation_m=20,
                        heart_rate_bpm=140 if with_heart_rate else None,
                        pace_s_per_km=580,
                    ),
                ),
                streams=(),
            )


def _mention(event_id: str, text: str) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text=text,
    )


if __name__ == "__main__":
    unittest.main()
