from __future__ import annotations

import unittest

from core.i18n import SupportedLanguage
from core.routing import RouteConfidence, WorkflowTarget
from llm.gateway import FakeLLMClient, LLMGateway, LLMGatewayError, LLMOperation, LLMRequest
from llm.operations import (
    ChatReplyInput,
    IntentClassificationInput,
    VisualizationIntentInput,
    WorkoutReplyInput,
    WorkoutReferenceInput,
    classify_intent,
    extract_visualization_intent,
    extract_workout_reference,
    write_chat_reply,
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
        gateway = LLMGateway(
            FakeLLMClient(
                {
                    LLMOperation.WORKOUT_REFERENCE_EXTRACTION: {
                        "selector_type": "latest",
                        "selector_value": "latest",
                        "matched_workout_ids": [],
                        "ambiguity_reason": "",
                        "requires_clarification": False,
                    }
                }
            )
        )

        reference = extract_workout_reference(gateway, WorkoutReferenceInput(user_text="viimeisin treeni"))

        self.assertEqual(reference.selector_type, "latest")
        self.assertFalse(reference.requires_clarification)

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


if __name__ == "__main__":
    unittest.main()
