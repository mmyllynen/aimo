from __future__ import annotations

import json
import unittest

from llm.gateway import LLMGateway, LLMGatewayError, LLMOperation, LLMRequest
from llm.operations import VisualizationIntentInput, extract_visualization_intent
from llm.openai_client import OpenAIClientConfig, OpenAIResponsesClient


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests = []
        self.timeouts = []

    def __call__(self, request, *, timeout: float):
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeHTTPResponse(self.payload)


class OpenAIResponsesClientTests(unittest.TestCase):
    def test_complete_json_posts_responses_request_and_parses_output_text(self) -> None:
        opener = FakeOpener(
            {
                "status": "completed",
                "output_text": json.dumps({"reply_text": "Hei", "tone": "concise", "should_update_summary": False}),
            }
        )
        client = OpenAIResponsesClient(
            OpenAIClientConfig(api_key="test-key", model="gpt-test", base_url="https://example.test/v1", timeout_s=5),
            opener=opener,
        )

        response = client.complete_json(_chat_request())

        self.assertEqual(response.payload["reply_text"], "Hei")
        self.assertEqual(opener.requests[0].full_url, "https://example.test/v1/responses")
        self.assertEqual(opener.requests[0].headers["Authorization"], "Bearer test-key")
        self.assertEqual(opener.timeouts, [5])
        body = json.loads(opener.requests[0].data.decode("utf-8"))
        self.assertEqual(body["model"], "gpt-test")
        self.assertEqual(body["instructions"], "reply")
        self.assertEqual(body["max_output_tokens"], 100)
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertEqual(body["text"]["format"]["schema"]["required"], ["reply_text", "tone", "should_update_summary"])
        self.assertFalse(body["text"]["format"]["schema"]["additionalProperties"])
        model_input = json.loads(body["input"])
        self.assertEqual(model_input["operation"], "chat_reply")
        self.assertEqual(model_input["payload"]["user_text"], "moi")

    def test_complete_json_parses_nested_output_content(self) -> None:
        opener = FakeOpener(
            {
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"reply_text": "Hi", "tone": "concise", "should_update_summary": True}),
                            }
                        ]
                    }
                ],
            }
        )
        client = OpenAIResponsesClient(OpenAIClientConfig(api_key="test-key", model="gpt-test"), opener=opener)

        response = client.complete_json(_chat_request())

        self.assertEqual(response.payload["should_update_summary"], True)

    def test_request_schema_preserves_array_item_types(self) -> None:
        opener = FakeOpener(
            {
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "reply_text": "Hyvä treeni.",
                        "claims_used": ["distance"],
                        "missing_data_notes": [],
                    }
                ),
            }
        )
        client = OpenAIResponsesClient(OpenAIClientConfig(api_key="test-key", model="gpt-test"), opener=opener)

        client.complete_json(_workout_request())

        body = json.loads(opener.requests[0].data.decode("utf-8"))
        properties = body["text"]["format"]["schema"]["properties"]
        self.assertEqual(properties["claims_used"]["items"], {"type": "string"})
        self.assertEqual(properties["missing_data_notes"]["items"], {"type": "string"})

    def test_request_schema_closes_nested_object_properties(self) -> None:
        opener = FakeOpener(
            {
                "status": "completed",
                "output_text": json.dumps(
                    {
                        "workout_selector": {"type": "latest", "value": "", "count": None, "limit": None},
                        "x_metric": "elapsed_s",
                        "requested_metrics": ["heart_rate_bpm"],
                        "transform_hints": [],
                        "date_range": {"start": "", "end": ""},
                        "comparison_mode": "",
                        "layout_mode": "auto",
                        "chart_kind": "auto",
                        "context_update": {"set_current_workout": False},
                    }
                ),
            }
        )
        client = OpenAIResponsesClient(OpenAIClientConfig(api_key="test-key", model="gpt-test"), opener=opener)

        extract_visualization_intent(LLMGateway(client), VisualizationIntentInput(user_text="draw heart rate"))

        body = json.loads(opener.requests[0].data.decode("utf-8"))
        properties = body["text"]["format"]["schema"]["properties"]
        workout_selector = properties["workout_selector"]
        date_range = properties["date_range"]
        context_update = properties["context_update"]
        self.assertFalse(workout_selector["additionalProperties"])
        self.assertEqual(workout_selector["required"], ["type", "value", "count", "limit"])
        self.assertIn("latest", workout_selector["properties"]["type"]["enum"])
        self.assertEqual(workout_selector["properties"]["count"]["type"], ["integer", "null"])
        self.assertIn("heart_rate_bpm", properties["requested_metrics"]["items"]["enum"])
        self.assertNotIn("heart_rate", properties["requested_metrics"]["items"]["enum"])
        self.assertEqual(properties["layout_mode"]["enum"], ["auto", "single_axis", "small_multiples"])
        self.assertEqual(properties["chart_kind"]["enum"], ["auto", "line", "bar", "pie"])
        self.assertIn("chart_kind", body["text"]["format"]["schema"]["required"])
        self.assertIn("context_update", body["text"]["format"]["schema"]["required"])
        self.assertFalse(context_update["additionalProperties"])
        self.assertEqual(context_update["required"], ["set_current_workout"])
        self.assertFalse(date_range["additionalProperties"])
        self.assertEqual(date_range["required"], ["start", "end"])

    def test_complete_json_rejects_missing_json_output(self) -> None:
        opener = FakeOpener({"status": "completed", "output_text": "not-json"})
        client = OpenAIResponsesClient(OpenAIClientConfig(api_key="test-key", model="gpt-test"), opener=opener)

        with self.assertRaises(LLMGatewayError):
            client.complete_json(_chat_request())

    def test_requires_api_key_and_model(self) -> None:
        with self.assertRaises(LLMGatewayError):
            OpenAIResponsesClient(OpenAIClientConfig(api_key="", model="gpt-test"))
        with self.assertRaises(LLMGatewayError):
            OpenAIResponsesClient(OpenAIClientConfig(api_key="test-key", model=""))


def _chat_request() -> LLMRequest:
    return LLMRequest(
        operation=LLMOperation.CHAT_REPLY,
        system_prompt="reply",
        user_payload={"user_text": "moi"},
        response_schema={
            "required": ["reply_text", "tone", "should_update_summary"],
            "properties": {
                "reply_text": {"type": "string"},
                "tone": {"type": "string"},
                "should_update_summary": {"type": "boolean"},
            },
        },
        max_tokens=100,
    )


def _workout_request() -> LLMRequest:
    return LLMRequest(
        operation=LLMOperation.WORKOUT_REPLY,
        system_prompt="reply",
        user_payload={"user_text": "analysoi viimeisin treeni"},
        response_schema={
            "required": ["reply_text", "claims_used", "missing_data_notes"],
            "properties": {
                "reply_text": {"type": "string"},
                "claims_used": {"type": "array", "items": {"type": "string"}},
                "missing_data_notes": {"type": "array", "items": {"type": "string"}},
            },
        },
        max_tokens=100,
    )


if __name__ == "__main__":
    unittest.main()
