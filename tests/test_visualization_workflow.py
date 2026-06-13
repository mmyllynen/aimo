from __future__ import annotations

import unittest

from app.dispatcher import DispatchContext, Dispatcher, route_event
from core.events import CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.routing import WorkflowTarget
from core.workflows import OutgoingKind, WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.repositories import WorkoutPointRecord, WorkoutRecord
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
                    "chart_family": "line",
                    "x_metric": "elapsed_s",
                    "y_metrics": ["heart_rate_bpm"],
                    "transforms": [],
                    "date_range": {},
                    "comparison_mode": "",
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
        self.assertEqual(client.requests[0].operation, LLMOperation.VISUALIZATION_INTENT)
        self.assertNotIn("workout_points", client.requests[0].user_payload)
        self.assertNotIn("raw_points", client.requests[0].user_payload)

    def test_route_event_marks_chart_language_as_visualization(self) -> None:
        route = route_event(_mention("event-1", "piirrä kuvaaja viimeisimmästä treenistä"))

        self.assertEqual(route.target, WorkflowTarget.VISUALIZATION)

    def _seed_workout(self, *, with_heart_rate: bool) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            workout = WorkoutRecord(
                workout_id="workout-1",
                owner_user_id="user-1",
                source_attachment_id=None,
                guild_id="guild-1",
                channel_id="channel-1",
                title="Morning run",
                kind="activity",
                primary_kind="activity",
                start_time_utc="2026-06-13T07:00:00Z",
                start_time_local="2026-06-13T10:00:00+03:00",
                local_date="2026-06-13",
                distance_km=1.0,
                duration_s=600,
                pace_s_per_km=600,
                ascent_m=10,
                avg_hr_bpm=130 if with_heart_rate else None,
                max_hr_bpm=140 if with_heart_rate else None,
                point_count=3,
                created_at="2026-06-13T10:30:00Z",
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
