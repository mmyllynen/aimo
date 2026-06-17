from __future__ import annotations

import unittest

from core.i18n import SupportedLanguage
from core.routing import RouteConfidence, WorkflowTarget
from llm.gateway import FakeLLMClient, LLMGateway, LLMGatewayError, LLMOperation, LLMRequest
from llm.operations import (
    ChatReplyInput,
    IntentClassificationInput,
    PeriodAnalysisReplyInput,
    PeriodRequestInput,
    VisualizationIntentInput,
    VisualizationIntentRevisionInput,
    WorkoutReplyInput,
    WorkoutReferenceInput,
    classify_intent,
    extract_visualization_intent,
    extract_workout_reference,
    interpret_period_request,
    revise_visualization_intent,
    write_chat_reply,
    write_period_analysis_reply,
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
