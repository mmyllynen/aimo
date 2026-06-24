from __future__ import annotations

import unittest

from core.i18n import SupportedLanguage
from core.routing import RouteConfidence, WorkflowTarget
from llm.gateway import FakeLLMClient, LLMGateway, LLMGatewayError, LLMOperation, LLMRequest
from llm.operations import (
    ChatReplyInput,
    GpxTitleInput,
    IntentClassificationInput,
    PeriodAnalysisReplyInput,
    PeriodRequestInput,
    RouteTimeEstimateExplanationIntentInput,
    RouteTimeEstimateExplanationReplyInput,
    RouteTimeEstimateIntentInput,
    RouteTimeEstimateReplyInput,
    VisualizationIntentInput,
    VisualizationIntentRevisionInput,
    WorkoutReplyInput,
    WorkoutReferenceInput,
    classify_intent,
    extract_gpx_title,
    extract_visualization_intent,
    extract_workout_reference,
    interpret_route_time_estimate_explanation_intent,
    interpret_route_time_estimate_intent,
    interpret_period_request,
    revise_visualization_intent,
    write_chat_reply,
    write_period_analysis_reply,
    write_route_time_estimate_explanation_reply,
    write_route_time_estimate_reply,
    write_workout_reply,
)


class LLMGatewayTests(unittest.TestCase):
    def test_classify_intent_validates_and_maps_route_decision(self) -> None:
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.INTENT_CLASSIFICATION: {
                        "workflow": "visualization",
                        "confidence": "high",
                        "slots": {"workout_selector": "latest"},
                        "clarification": "",
                        "reason": "User asked for a chart.",
                    }
                }
            )
        )

        decision = classify_intent(
            gateway,
            IntentClassificationInput(
                event_kind="mention",
                user_text="piirra viimeisin treeni",
                has_attachments=False,
            ),
        )

        self.assertEqual(decision.target, WorkflowTarget.VISUALIZATION)
        self.assertEqual(decision.confidence, RouteConfidence.HIGH)
        self.assertEqual(decision.slots["workout_selector"], "latest")
        request = gateway.client.requests[0]
        self.assertIn("Use visualization for any request", request.system_prompt)
        self.assertIn("do not route workout chart requests to chat", request.system_prompt)
        self.assertIn("visualization", request.user_payload["workflow_catalog"])
        self.assertIn("sykealuejakauma", request.user_payload["workflow_catalog"]["visualization"]["examples"][0])

    def test_extract_gpx_title_returns_explicit_title(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.GPX_TITLE_EXTRACTION: {
                    "title": "Aamulenkki 18.6.",
                }
            }
        )

        title = extract_gpx_title(
            LLMGateway(client),
            GpxTitleInput(
                user_text='tallenna tämä ja anna sille nimeksi "Aamulenkki 18.6."',
                attachment_count=1,
            ),
        )

        self.assertEqual(title.title, "Aamulenkki 18.6.")
        self.assertEqual(client.requests[0].operation, LLMOperation.GPX_TITLE_EXTRACTION)
        self.assertEqual(client.requests[0].user_payload["attachment_count"], 1)
        self.assertIn("reittisuunnitelma", client.requests[0].system_prompt)
        self.assertIn("nimeä se", client.requests[0].system_prompt)
        self.assertIn("call it", client.requests[0].system_prompt)
        self.assertIn("Juhannusreitti", client.requests[0].system_prompt)

    def test_rejects_malformed_model_output(self) -> None:
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.INTENT_CLASSIFICATION: {
                        "workflow": "visualization",
                        "confidence": "high",
                    }
                }
            )
        )

        with self.assertRaises(LLMGatewayError):
            classify_intent(
                gateway,
                IntentClassificationInput(
                    event_kind="mention",
                    user_text="piirra",
                    has_attachments=False,
                ),
            )

    def test_rejects_forbidden_raw_workout_points_in_input(self) -> None:
        gateway = LLMGateway(FakeLLMClient({}))

        with self.assertRaises(LLMGatewayError):
            gateway.run(
                LLMRequest(
                    operation=LLMOperation.INTENT_CLASSIFICATION,
                    system_prompt="test",
                    user_payload={"workout_points": [{"heart_rate": 120}]},
                    response_schema={"required": [], "properties": {}},
                    max_tokens=100,
                )
            )

    def test_extract_workout_reference_preserves_latest_selector(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.WORKOUT_REFERENCE_EXTRACTION: {
                    "selector_type": "latest",
                    "selector_value": "latest",
                    "matched_workout_ids": [],
                    "ambiguity_reason": "",
                    "requires_clarification": False,
                    "set_current_workout": False,
                }
            }
        )
        gateway = LLMGateway(client)

        reference = extract_workout_reference(gateway, WorkoutReferenceInput(user_text="viimeisin treeni"))

        self.assertEqual(reference.selector_type, "latest")
        self.assertFalse(reference.requires_clarification)
        self.assertEqual(client.requests[0].max_tokens, 1200)

    def test_interpret_period_request_returns_structured_scope(self) -> None:
        client = FakeLLMClient(
            {
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
                }
            }
        )

        request = interpret_period_request(
            LLMGateway(client),
            PeriodRequestInput(
                user_text="tee yhteenveto kaikkien treenien nousumetreistä",
                current_datetime="2026-06-16T16:00:00+03:00",
                timezone="Europe/Helsinki",
            ),
        )

        self.assertTrue(request.is_period_request)
        self.assertEqual(request.scope_type, "all_workouts")
        self.assertEqual(request.metrics, ("ascent_m",))
        self.assertIn("allowed_scope_types", client.requests[0].user_payload)
        self.assertIn("Python resolves dates", client.requests[0].system_prompt)

    def test_write_period_analysis_reply_uses_bounded_period_facts(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.PERIOD_ANALYSIS_REPLY: {
                    "reply_text": "Yhteensä 50 m nousua.",
                    "claims_used": ["ascent_m"],
                    "missing_data_notes": [],
                }
            }
        )

        reply = write_period_analysis_reply(
            LLMGateway(client),
            PeriodAnalysisReplyInput(
                user_text="nousumetrit",
                period_facts={
                    "workout_count": 2,
                    "summary": {"ascent_m": {"sum": 50}},
                },
            ),
            language=SupportedLanguage.FI,
        )

        self.assertEqual(reply.reply_text, "Yhteensä 50 m nousua.")
        self.assertNotIn("workout_points", client.requests[0].user_payload)
        self.assertIn("Respond in fi", client.requests[0].system_prompt)

    def test_interpret_route_time_estimate_intent_returns_boolean_intent(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.ROUTE_TIME_ESTIMATE_INTENT: {
                    "is_route_time_estimate": True,
                    "activity_intent": "run",
                    "target_date": "2026-06-20",
                    "target_time_of_day": "",
                    "reason": "User asked how long a route would take.",
                }
            }
        )

        intent = interpret_route_time_estimate_intent(
            LLMGateway(client),
            RouteTimeEstimateIntentInput(
                user_text="paljonko tähän reittiin menisi?",
                current_date="2026-06-18",
                timezone="Europe/Helsinki",
                compact_routing_context={"active_workout_id": "workout-1"},
            ),
        )

        self.assertTrue(intent.is_route_time_estimate)
        self.assertEqual(intent.activity_intent, "run")
        self.assertEqual(intent.target_date, "2026-06-20")
        self.assertEqual(client.requests[0].operation, LLMOperation.ROUTE_TIME_ESTIMATE_INTENT)
        self.assertIn("Do not calculate time", client.requests[0].system_prompt)

    def test_write_route_time_estimate_reply_uses_estimate_facts(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.ROUTE_TIME_ESTIMATE_REPLY: {
                    "reply_text": "Arvio on noin 35 minuuttia.",
                    "claims_used": ["estimate_s", "route_distance_km"],
                    "missing_data_notes": ["ascent_m"],
                }
            }
        )

        reply = write_route_time_estimate_reply(
            LLMGateway(client),
            RouteTimeEstimateReplyInput(
                user_text="kauanko tähän menee?",
                estimate_facts={
                    "workout_id": "workout-1",
                    "estimate_s": 2100,
                    "estimate_text": "35 min",
                    "route_distance_km": 6.0,
                    "missing_data": ["ascent_m"],
                },
            ),
            language=SupportedLanguage.FI,
        )

        self.assertEqual(reply.reply_text, "Arvio on noin 35 minuuttia.")
        self.assertEqual(reply.missing_data_notes, ("ascent_m",))
        self.assertIn("estimate_facts", client.requests[0].user_payload)
        self.assertIn("Do not invent pace", client.requests[0].system_prompt)

    def test_interpret_route_time_estimate_explanation_intent_returns_boolean_intent(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_INTENT: {
                    "is_explanation_request": True,
                    "reason": "User asked why the estimate was produced.",
                }
            }
        )

        intent = interpret_route_time_estimate_explanation_intent(
            LLMGateway(client),
            RouteTimeEstimateExplanationIntentInput(
                user_text="millä perusteella tuo arvio tuli?",
                compact_routing_context={"has_recent_route_time_estimate": True},
            ),
        )

        self.assertTrue(intent.is_explanation_request)
        self.assertEqual(client.requests[0].operation, LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_INTENT)
        self.assertIn("previous route time estimate", client.requests[0].system_prompt)

    def test_write_route_time_estimate_explanation_reply_uses_explanation_facts(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.ROUTE_TIME_ESTIMATE_EXPLANATION_REPLY: {
                    "reply_text": "Arvio perustui painotettuun vertailuun.",
                    "claims_used": ["model", "baseline_pace_text"],
                    "missing_data_notes": [],
                }
            }
        )

        reply = write_route_time_estimate_explanation_reply(
            LLMGateway(client),
            RouteTimeEstimateExplanationReplyInput(
                user_text="avaa laskenta",
                explanation_facts={
                    "model": "feature_similarity",
                    "baseline_pace_text": "8:05 min/km",
                    "comparable_count": 9,
                },
            ),
            language=SupportedLanguage.FI,
        )

        self.assertEqual(reply.reply_text, "Arvio perustui painotettuun vertailuun.")
        self.assertIn("explanation_facts", client.requests[0].user_payload)
        self.assertIn("Do not invent workouts", client.requests[0].system_prompt)

    def test_chat_reply_includes_configured_language_instruction(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.CHAT_REPLY: {
                    "reply_text": "Sure.",
                    "tone": "concise",
                    "should_update_summary": True,
                }
            }
        )
        gateway = LLMGateway(client)

        reply = write_chat_reply(
            gateway,
            ChatReplyInput(user_text="hello"),
            language=SupportedLanguage.EN,
        )

        self.assertEqual(reply.reply_text, "Sure.")
        self.assertIn("Respond in en", client.requests[0].system_prompt)
        self.assertIn("Use workflow_facts and capabilities as ground truth", client.requests[0].system_prompt)
        self.assertIn("Do not claim integrations", client.requests[0].system_prompt)

    def test_extract_visualization_intent_returns_structured_intent(self) -> None:
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.VISUALIZATION_INTENT: {
                        "workout_selector": {"type": "latest"},
                        "x_metric": "elapsed_s",
                        "requested_metrics": ["heart_rate_bpm"],
                        "transform_hints": [],
                        "date_range": {},
                        "comparison_mode": "",
                        "layout_mode": "auto",
                        "chart_kind": "auto",
                        "output_mode": "chart",
                        "context_update": {"set_current_workout": False},
                    }
                }
            )
        )

        intent = extract_visualization_intent(
            gateway,
            VisualizationIntentInput(user_text="draw heart rate"),
        )

        self.assertEqual(intent.workout_selector["type"], "latest")
        self.assertEqual(intent.y_metrics, ("heart_rate_bpm",))
        self.assertEqual(intent.layout_mode, "auto")
        self.assertEqual(intent.chart_kind, "auto")
        request = gateway.client.requests[0]
        self.assertIn("active_workout", request.system_prompt)
        self.assertIn("prefer workout_selector type active", request.system_prompt)
        self.assertIn("Use latest only for explicit", request.system_prompt)
        self.assertIn("näytä reitti kartalla", request.system_prompt)
        self.assertIn("not social_image", request.system_prompt)

    def test_extract_visualization_intent_accepts_route_map_intent(self) -> None:
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.VISUALIZATION_INTENT: {
                        "workout_selector": {"type": "latest"},
                        "x_metric": "longitude",
                        "requested_metrics": ["route"],
                        "transform_hints": [],
                        "date_range": {},
                        "comparison_mode": "",
                        "layout_mode": "auto",
                        "chart_kind": "map",
                        "output_mode": "chart",
                        "context_update": {"set_current_workout": False},
                    }
                }
            )
        )

        intent = extract_visualization_intent(
            gateway,
            VisualizationIntentInput(user_text="piirrä reitti kartalle"),
        )

        self.assertEqual(intent.x_metric, "longitude")
        self.assertEqual(intent.y_metrics, ("route",))
        self.assertEqual(intent.chart_kind, "map")

    def test_extract_visualization_intent_accepts_social_image_output_mode(self) -> None:
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.VISUALIZATION_INTENT: {
                        "workout_selector": {"type": "latest"},
                        "x_metric": "longitude",
                        "requested_metrics": ["route", "distance_km", "duration_s"],
                        "transform_hints": [],
                        "date_range": {},
                        "comparison_mode": "",
                        "layout_mode": "auto",
                        "chart_kind": "map",
                        "output_mode": "social_image",
                        "social_style": {"preset": "poster", "route": "white", "dim": 35},
                        "context_update": {"set_current_workout": False},
                    }
                }
            )
        )

        intent = extract_visualization_intent(
            gateway,
            VisualizationIntentInput(user_text="piirrä somekuva viimeisestä treenistä"),
        )

        self.assertEqual(intent.output_mode, "social_image")
        self.assertEqual(intent.y_metrics, ("route", "distance_km", "duration_s"))
        self.assertEqual(intent.social_style, {"preset": "poster", "route": "white", "dim": 35})

    def test_revise_visualization_intent_uses_typed_operation(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.VISUALIZATION_INTENT_REVISION: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["heart_rate_bpm"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                    "chart_kind": "auto",
                    "output_mode": "chart",
                    "context_update": {"set_current_workout": False},
                }
            }
        )

        intent = revise_visualization_intent(
            LLMGateway(client),
            VisualizationIntentRevisionInput(
                user_text="draw latest chart",
                failed_intent={"y_metrics": ["invented_metric"]},
                validation_errors=(
                    {
                        "code": "unsupported_column",
                        "path": "metric_or_encoding",
                        "value": "invented_metric",
                        "allowed_values": ["heart_rate_bpm"],
                    },
                ),
                dataset_manifest={"datasets": []},
                allowed_primitives={"chart_kinds": ["auto", "line"]},
            ),
        )

        self.assertEqual(intent.y_metrics, ("heart_rate_bpm",))
        self.assertEqual(client.requests[0].operation, LLMOperation.VISUALIZATION_INTENT_REVISION)
        self.assertIn("full replacement intent", client.requests[0].system_prompt)

    def test_write_workout_reply_uses_bounded_workout_facts(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.WORKOUT_REPLY: {
                    "reply_text": "Good aerobic run.",
                    "claims_used": ["distance_km", "avg_hr_bpm"],
                    "missing_data_notes": [],
                }
            }
        )
        gateway = LLMGateway(client)

        reply = write_workout_reply(
            gateway,
            WorkoutReplyInput(
                user_text="how was my latest workout?",
                resolved_workout_facts={
                    "workout_id": "workout-1",
                    "distance_km": 5.0,
                    "stream_manifest": [{"stream_key": "heart_rate", "sample_count": 100}],
                },
            ),
            language=SupportedLanguage.EN,
        )

        self.assertEqual(reply.reply_text, "Good aerobic run.")
        self.assertIn("Respond in en", client.requests[0].system_prompt)
        self.assertNotIn("workout_points", client.requests[0].user_payload)

    def test_gateway_observer_receives_success_and_error_traces(self) -> None:
        traces = []
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.CHAT_REPLY: {
                        "reply_text": "Sure.",
                        "tone": "concise",
                        "should_update_summary": False,
                    }
                }
            ),
            observer=traces.append,
        )

        write_chat_reply(gateway, ChatReplyInput(user_text="hello"), language=SupportedLanguage.EN)
        with self.assertRaises(LLMGatewayError):
            gateway.run(
                LLMRequest(
                    operation=LLMOperation.CHAT_REPLY,
                    system_prompt="bad",
                    user_payload={"raw_points": []},
                    response_schema={"required": [], "properties": {}},
                    max_tokens=100,
                )
            )

        self.assertEqual(traces[0].operation, LLMOperation.CHAT_REPLY)
        self.assertEqual(traces[0].status, "success")
        self.assertEqual(traces[0].response_keys, ("reply_text", "should_update_summary", "tone"))
        self.assertGreaterEqual(traces[0].duration_ms, 0)
        self.assertEqual(traces[1].status, "error")
        self.assertEqual(traces[1].error_type, "LLMGatewayError")
        self.assertIn("Forbidden large/raw payload field", traces[1].error_message)


if __name__ == "__main__":
    unittest.main()
