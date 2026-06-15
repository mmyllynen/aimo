from __future__ import annotations

import unittest

from app.dispatcher import DispatchContext, Dispatcher, route_event
from core.events import CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.routing import WorkflowTarget
from core.workflows import WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.repositories import WorkoutPointRecord, WorkoutRecord, WorkoutStreamRecord
from storage.unit_of_work import UnitOfWork, open_database


class WorkoutChatWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_latest_workout_chat_uses_bounded_facts_and_persists_reply(self) -> None:
        self._seed_workouts()
        client = _workout_client("Hyvä aerobinen treeni.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi viimeisin treeni"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].text, "Hyvä aerobinen treeni.")
        payload = _request_payload(client, LLMOperation.WORKOUT_REPLY)
        self.assertEqual(payload["resolved_workout_facts"]["workout_id"], "workout-2")
        self.assertEqual(payload["resolved_workout_facts"]["stream_manifest"][0]["stream_key"], "heart_rate")
        self.assertNotIn("workout_points", payload)
        self.assertNotIn("raw_points", payload)
        with UnitOfWork(self.connection) as repositories:
            history = repositories.history.list_recent_for_channel("channel-1")
        self.assertEqual(history[-1].role, "assistant")
        self.assertEqual(history[-1].event_type, "workout_reply")

    def test_active_workout_chat_resolves_active_workout(self) -> None:
        self._seed_workouts()
        with UnitOfWork(self.connection) as repositories:
            repositories.active_workouts.set(
                user_id="user-1",
                workout_id="workout-1",
                updated_at="2026-06-13T11:00:00Z",
            )
        client = _workout_client("Aktiivinen treeni oli kevyt.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "miten aktiivinen treeni meni?"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_request_payload(client, LLMOperation.WORKOUT_REPLY)["resolved_workout_facts"]["workout_id"], "workout-1")

    def test_workout_chat_resolves_list_index_reference(self) -> None:
        self._seed_workouts()
        client = _workout_client("Listan ensimmäinen treeni.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi treeni #1"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_request_payload(client, LLMOperation.WORKOUT_REPLY)["resolved_workout_facts"]["workout_id"], "workout-2")

    def test_workout_chat_reports_ambiguous_date_reference(self) -> None:
        self._seed_workouts()
        client = _workout_client("Ei käytetä.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi 2026-06-13 treeni"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_AMBIGUOUS_WORKOUT)
        self.assertFalse([request for request in client.requests if request.operation == LLMOperation.WORKOUT_REPLY])

    def test_missing_summary_facts_are_explicit_in_llm_input(self) -> None:
        self._seed_workouts(avg_hr=None)
        client = _workout_client("Sykedata puuttuu, mutta matka ja kesto löytyvät.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "arvioi viimeisin treeni"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("avg_hr_bpm", _request_payload(client, LLMOperation.WORKOUT_REPLY)["missing_data_facts"])

    def test_workout_chat_without_gateway_returns_model_error(self) -> None:
        self._seed_workouts()

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi viimeisin treeni"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SYSTEM_ERROR)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_MODEL_UNAVAILABLE)

    def test_route_event_marks_workout_question_as_workout_chat(self) -> None:
        route = route_event(_mention("event-1", "miten viimeisin treeni meni?"))

        self.assertEqual(route.target, WorkflowTarget.WORKOUT_CHAT)

    def _seed_workouts(self, *, avg_hr: float | None = 132) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            for workout in (
                WorkoutRecord(
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
                    distance_km=5.0,
                    duration_s=1800,
                    pace_s_per_km=360,
                    ascent_m=20,
                    avg_hr_bpm=130,
                    max_hr_bpm=150,
                    point_count=2,
                    created_at="2026-06-13T10:30:00Z",
                ),
                WorkoutRecord(
                    workout_id="workout-2",
                    owner_user_id="user-1",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Evening run",
                    kind="activity",
                    primary_kind="activity",
                    start_time_utc="2026-06-13T16:00:00Z",
                    start_time_local="2026-06-13T19:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=6.0,
                    duration_s=2100,
                    pace_s_per_km=350,
                    ascent_m=30,
                    avg_hr_bpm=avg_hr,
                    max_hr_bpm=152 if avg_hr is not None else None,
                    point_count=2,
                    created_at="2026-06-13T19:40:00Z",
                ),
            ):
                repositories.workouts.add(workout)
            repositories.workout_streams.replace_for_workout(
                "workout-2",
                points=(
                    WorkoutPointRecord(workout_id="workout-2", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                    WorkoutPointRecord(workout_id="workout-2", point_index=1, elapsed_s=300, heart_rate_bpm=132),
                ),
                streams=(
                    WorkoutStreamRecord(
                        workout_id="workout-2",
                        stream_key="heart_rate",
                        unit="bpm",
                        sample_count=2,
                        min_value=120,
                        max_value=132,
                        avg_value=126,
                    ),
                ),
            )


def _workout_client(reply_text: str) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.WORKOUT_REPLY: {
                "reply_text": reply_text,
                "claims_used": ["distance_km", "duration_s"],
                "missing_data_notes": [],
            }
        }
    )


def _request_payload(client: FakeLLMClient, operation: LLMOperation):
    return next(request.user_payload for request in client.requests if request.operation == operation)


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
