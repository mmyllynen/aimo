from __future__ import annotations

import unittest

from app.dispatcher import DispatchContext, Dispatcher, route_event
from core.events import CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.routing import WorkflowTarget
from core.workflows import WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMGatewayError, LLMOperation, LLMRequest, LLMResponse
from storage.repositories import WorkoutPointRecord, WorkoutRecord, WorkoutStreamRecord
from storage.unit_of_work import UnitOfWork, open_database
from workout.estimate_features import backfill_workout_estimate_features
from weather.service import WeatherFacts, WeatherLocation


class WorkoutChatWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_latest_workout_chat_uses_bounded_facts_and_persists_reply(self) -> None:
        self._seed_workouts()
        client = _workout_client("Hyvä aerobinen treeni.", selector_type="latest", selector_value="latest")

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
        client = _workout_client("Aktiivinen treeni oli kevyt.", selector_type="active", selector_value="active")

        result = self.dispatcher.dispatch(
            _mention("event-1", "miten aktiivinen treeni meni?"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_request_payload(client, LLMOperation.WORKOUT_REPLY)["resolved_workout_facts"]["workout_id"], "workout-1")

    def test_workout_chat_resolves_list_index_reference(self) -> None:
        self._seed_workouts()
        client = _workout_client("Listan ensimmäinen treeni.", matched_workout_ids=("workout-2",), set_current_workout=True)

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi treeni #1"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(_request_payload(client, LLMOperation.WORKOUT_REPLY)["resolved_workout_facts"]["workout_id"], "workout-2")
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-2")

    def test_workout_chat_reports_ambiguous_date_reference(self) -> None:
        self._seed_workouts()
        client = _workout_client(
            "Ei käytetä.",
            selector_type="date",
            selector_value="2026-06-13",
            matched_workout_ids=("workout-1", "workout-2"),
            requires_clarification=True,
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "analysoi 2026-06-13 treeni"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_AMBIGUOUS_WORKOUT)
        self.assertFalse([request for request in client.requests if request.operation == LLMOperation.WORKOUT_REPLY])

    def test_all_workouts_ascent_summary_uses_period_path(self) -> None:
        self._seed_workouts()
        client = _period_client("Kahdessa treenissä oli yhteensä 50 m nousua.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "tee yhteenveto kaikkien treenien nousumetreistä"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].text, "Kahdessa treenissä oli yhteensä 50 m nousua.")
        payload = _request_payload(client, LLMOperation.PERIOD_ANALYSIS_REPLY)
        self.assertEqual(payload["period_facts"]["workout_count"], 2)
        self.assertEqual(payload["period_facts"]["summary"]["ascent_m"]["sum"], 50)
        self.assertFalse([request for request in client.requests if request.operation == LLMOperation.WORKOUT_REFERENCE_EXTRACTION])

    def test_missing_summary_facts_are_explicit_in_llm_input(self) -> None:
        self._seed_workouts(avg_hr=None)
        client = _workout_client("Sykedata puuttuu, mutta matka ja kesto löytyvät.", selector_type="latest", selector_value="latest")

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

    def test_route_event_uses_llm_for_workout_question(self) -> None:
        client = FakeLLMClient({LLMOperation.INTENT_CLASSIFICATION: _classification()})

        route = route_event(_mention("event-1", "miten viimeisin treeni meni?"), llm_gateway=LLMGateway(client))

        self.assertEqual(route.target, WorkflowTarget.WORKOUT_CHAT)

    def test_route_event_uses_workout_chat_for_route_time_estimate_modifier(self) -> None:
        route = route_event(_mention("event-1", "paljonko tähän menisi +estimate"))

        self.assertEqual(route.target, WorkflowTarget.WORKOUT_CHAT)
        self.assertEqual(route.slots["route_time_estimate"], True)

    def test_route_time_estimate_uses_user_history_without_workout_reply_generation(self) -> None:
        self._seed_workouts()
        client = _workout_client("Ei käytetä.", selector_type="latest", selector_value="latest")

        result = self.dispatcher.dispatch(
            _mention("event-1", "paljonko viimeisimpään reittiin menisi +ennuste"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Arvio tälle reitille", result.messages[0].text)
        self.assertIn("perustuu 1 tallennettuun vertailutreeniin", result.messages[0].text)
        self.assertEqual(result.messages[0].metadata["route_time_comparable_count"], 1)
        self.assertEqual(result.messages[0].metadata["route_time_confidence"], "low")
        self.assertFalse([request for request in client.requests if request.operation == LLMOperation.WORKOUT_REPLY])
        with UnitOfWork(self.connection) as repositories:
            history = repositories.history.list_recent_for_channel("channel-1")
        self.assertEqual(history[-1].event_type, "route_time_estimate")

    def test_route_time_estimate_can_use_default_workout_without_llm_gateway(self) -> None:
        self._seed_workouts()

        result = self.dispatcher.dispatch(
            _mention("event-1", "paljonko tähän menisi +estimate"),
            DispatchContext(UnitOfWork(self.connection), language=SupportedLanguage.FI),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Arvio tälle reitille", result.messages[0].text)
        self.assertEqual(result.messages[0].metadata["workout_id"], "workout-2")

    def test_freeform_route_time_estimate_uses_intent_and_conversational_reply(self) -> None:
        self._seed_workouts()
        client = _route_time_estimate_client("Tähän reittiin menisi arviolta noin 35 minuuttia.")

        result = self.dispatcher.dispatch(
            _mention("event-1", "paljonko viimeisimpään reittiin suunnilleen menisi aikaa?"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].text, "Tähän reittiin menisi arviolta noin 35 minuuttia.")
        self.assertTrue(result.messages[0].metadata["route_time_conversational"])
        self.assertEqual(result.messages[0].metadata["workout_id"], "workout-2")
        estimate_payload = _request_payload(client, LLMOperation.ROUTE_TIME_ESTIMATE_REPLY)
        self.assertEqual(estimate_payload["estimate_facts"]["workout_id"], "workout-2")
        self.assertEqual(estimate_payload["estimate_facts"]["comparable_workout_count"], 1)
        self.assertNotIn("workout_points", estimate_payload)
        self.assertNotIn("raw_points", estimate_payload)
        self.assertFalse([request for request in client.requests if request.operation == LLMOperation.WORKOUT_REPLY])

    def test_route_time_estimate_explanation_uses_previous_metadata_only(self) -> None:
        self._seed_workouts()
        with UnitOfWork(self.connection) as repositories:
            backfill_workout_estimate_features(repositories, owner_user_id="user-1", updated_at="2026-06-13T20:00:00Z")
        estimate_client = _route_time_estimate_client("Tähän reittiin menisi arviolta noin 35 minuuttia.")
        self.dispatcher.dispatch(
            _mention("event-1", "paljonko viimeisimpään reittiin menisi aikaa?"),
            DispatchContext(UnitOfWork(self.connection), language=SupportedLanguage.FI, llm_gateway=LLMGateway(estimate_client)),
        )
        explanation_client = _route_time_explanation_client("Arvio perustui feature_similarity-malliin ja yhteen vertailutreeniin.")

        result = self.dispatcher.dispatch(
            _mention("event-2", "avaa laskenta tiiviisti"),
            DispatchContext(UnitOfWork(self.connection), language=SupportedLanguage.FI, llm_gateway=LLMGateway(explanation_client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].text, "Arvio perustui feature_similarity-malliin ja yhteen vertailutreeniin.")
        payload = _request_payload(explanation_client, LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_REPLY)
        facts = payload["explanation_facts"]
        self.assertEqual(facts["model"], "feature_similarity")
        self.assertEqual(facts["comparable_count"], 1)
        self.assertIn("baseline_pace_text", facts)
        self.assertNotIn("workout_points", payload)
        self.assertNotIn("raw_points", payload)
        self.assertFalse([request for request in explanation_client.requests if request.operation == LLMOperation.WORKOUT_REPLY])

    def test_route_time_estimate_with_target_date_applies_weather_adjustment(self) -> None:
        self._seed_workouts()
        with UnitOfWork(self.connection) as repositories:
            backfill_workout_estimate_features(repositories, owner_user_id="user-1", updated_at="2026-06-13T20:00:00Z")
        client = _route_time_estimate_client(
            "Sääkorjattu arvio on noin 38 minuuttia.",
            activity_intent="run",
            target_date="2026-06-20",
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "arvioi juoksuaika tälle reitille ensi lauantaina"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
                weather_provider=_FakeWeatherProvider(),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        weather = result.messages[0].metadata["route_time_weather"]
        self.assertTrue(weather["available"])
        self.assertEqual(weather["source"], "forecast")
        self.assertGreater(weather["adjustment_s"], 0)
        payload = _request_payload(client, LLMOperation.ROUTE_TIME_ESTIMATE_REPLY)
        self.assertEqual(payload["estimate_facts"]["weather"]["target_date"], "2026-06-20")
        self.assertNotIn("raw_points", payload)

    def test_route_time_estimate_reply_llm_failure_uses_deterministic_fallback(self) -> None:
        self._seed_workouts()
        with UnitOfWork(self.connection) as repositories:
            backfill_workout_estimate_features(repositories, owner_user_id="user-1", updated_at="2026-06-13T20:00:00Z")
        client = _FailingRouteTimeReplyClient(
            {
                LLMOperation.INTENT_CLASSIFICATION: _classification(),
                LLMOperation.PERIOD_REQUEST_INTERPRETATION: _period_none(),
                LLMOperation.ROUTE_TIME_ESTIMATE_INTENT: _route_time_intent(
                    True,
                    activity_intent="run",
                    target_date="2026-06-20",
                ),
                LLMOperation.WORKOUT_REFERENCE_EXTRACTION: {
                    "selector_type": "latest",
                    "selector_value": "latest",
                    "matched_workout_ids": [],
                    "ambiguity_reason": "",
                    "requires_clarification": False,
                    "set_current_workout": False,
                },
            }
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "arvioi juoksuaika tälle reitille ensi lauantaina"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
                weather_provider=_FakeWeatherProvider(),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertIn("Arvio tälle reitille", result.messages[0].text)
        self.assertIn("Sääkorjattu arvio", result.messages[0].text)
        self.assertIn("route_time_reply_llm_unavailable", result.messages[0].metadata["missing_data_notes"])

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
                    WorkoutPointRecord(
                        workout_id="workout-2",
                        point_index=0,
                        elapsed_s=0,
                        latitude=60.17,
                        longitude=24.94,
                        heart_rate_bpm=120,
                    ),
                    WorkoutPointRecord(
                        workout_id="workout-2",
                        point_index=1,
                        elapsed_s=300,
                        latitude=60.18,
                        longitude=24.95,
                        heart_rate_bpm=132,
                    ),
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


def _workout_client(
    reply_text: str,
    *,
    selector_type: str = "general",
    selector_value: str = "",
    matched_workout_ids: tuple[str, ...] = (),
    requires_clarification: bool = False,
    set_current_workout: bool = False,
) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.INTENT_CLASSIFICATION: _classification(),
            LLMOperation.PERIOD_REQUEST_INTERPRETATION: _period_none(),
            LLMOperation.ROUTE_TIME_ESTIMATE_INTENT: _route_time_intent(False),
            LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_INTENT: _route_time_explanation_intent(False),
            LLMOperation.WORKOUT_REFERENCE_EXTRACTION: {
                "selector_type": selector_type,
                "selector_value": selector_value,
                "matched_workout_ids": list(matched_workout_ids),
                "ambiguity_reason": "ambiguous" if requires_clarification else "",
                "requires_clarification": requires_clarification,
                "set_current_workout": set_current_workout,
            },
            LLMOperation.WORKOUT_REPLY: {
                "reply_text": reply_text,
                "claims_used": ["distance_km", "duration_s"],
                "missing_data_notes": [],
            }
        }
    )


def _route_time_estimate_client(
    reply_text: str,
    *,
    activity_intent: str = "unknown",
    target_date: str = "",
) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.INTENT_CLASSIFICATION: _classification(),
            LLMOperation.PERIOD_REQUEST_INTERPRETATION: _period_none(),
            LLMOperation.ROUTE_TIME_ESTIMATE_INTENT: _route_time_intent(
                True,
                activity_intent=activity_intent,
                target_date=target_date,
            ),
            LLMOperation.WORKOUT_REFERENCE_EXTRACTION: {
                "selector_type": "latest",
                "selector_value": "latest",
                "matched_workout_ids": [],
                "ambiguity_reason": "",
                "requires_clarification": False,
                "set_current_workout": False,
            },
            LLMOperation.ROUTE_TIME_ESTIMATE_REPLY: {
                "reply_text": reply_text,
                "claims_used": ["estimate_s", "route_distance_km", "comparable_workout_count"],
                "missing_data_notes": [],
            },
        }
    )


def _route_time_explanation_client(reply_text: str) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.INTENT_CLASSIFICATION: _classification(),
            LLMOperation.PERIOD_REQUEST_INTERPRETATION: _period_none(),
            LLMOperation.ROUTE_TIME_ESTIMATE_INTENT: _route_time_intent(False),
            LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_INTENT: _route_time_explanation_intent(True),
            LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_REPLY: {
                "reply_text": reply_text,
                "claims_used": ["model", "comparable_count", "baseline_pace_text"],
                "missing_data_notes": [],
            },
        }
    )


def _period_client(reply_text: str) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.INTENT_CLASSIFICATION: _classification(),
            LLMOperation.PERIOD_REQUEST_INTERPRETATION: {
                "scope_type": "all_workouts",
                "scope_value": "",
                "start_date": "",
                "end_date": "",
                "rolling_days": None,
                "filters": {"kind": "", "primary_kind": "", "tags": []},
                "metrics": ["ascent_m"],
                "grouping": "none",
                "output_mode": "prose",
                "comparison_mode": "none",
                "reason": "User asked for all workouts.",
            },
            LLMOperation.PERIOD_ANALYSIS_REPLY: {
                "reply_text": reply_text,
                "claims_used": ["ascent_m"],
                "missing_data_notes": [],
            },
        }
    )


def _period_none() -> dict[str, object]:
    return {
        "scope_type": "none",
        "scope_value": "",
        "start_date": "",
        "end_date": "",
        "rolling_days": None,
        "filters": {"kind": "", "primary_kind": "", "tags": []},
        "metrics": [],
        "grouping": "none",
        "output_mode": "prose",
        "comparison_mode": "none",
        "reason": "Single-workout request.",
    }


def _route_time_intent(
    is_route_time_estimate: bool,
    *,
    activity_intent: str = "unknown",
    target_date: str = "",
) -> dict[str, object]:
    return {
        "is_route_time_estimate": is_route_time_estimate,
        "activity_intent": activity_intent,
        "target_date": target_date,
        "target_time_of_day": "",
        "reason": "Route time estimate request." if is_route_time_estimate else "Not a route time estimate request.",
    }


def _route_time_explanation_intent(is_explanation_request: bool) -> dict[str, object]:
    return {
        "is_explanation_request": is_explanation_request,
        "reason": "Explain previous estimate." if is_explanation_request else "Not an explanation request.",
    }


def _classification() -> dict[str, object]:
    return {
        "workflow": "workout_chat",
        "confidence": "high",
        "slots": {},
        "clarification": "",
        "reason": "LLM classified the request as workout chat.",
    }


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


class _FakeWeatherProvider:
    def get_weather(self, location: WeatherLocation, target_date):
        return WeatherFacts(
            target_date=target_date.isoformat(),
            latitude=location.latitude,
            longitude=location.longitude,
            source="forecast",
            temperature_c=30.0,
            apparent_temperature_c=33.0,
            humidity_percent=55.0,
            wind_speed_m_s=4.0,
            wind_gust_m_s=7.0,
            precipitation_mm=0.0,
            precipitation_probability=10.0,
            snow_mm=0.0,
        )


class _FailingRouteTimeReplyClient(FakeLLMClient):
    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.operation == LLMOperation.ROUTE_TIME_ESTIMATE_REPLY:
            raise LLMGatewayError("OpenAI response status was 'incomplete' (max_output_tokens)")
        if request.operation not in self.responses:
            raise LLMGatewayError(f"No fake response configured for {request.operation}")
        return LLMResponse(payload=self.responses[request.operation])


if __name__ == "__main__":
    unittest.main()
