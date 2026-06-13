from __future__ import annotations

import json
import unittest

from llm.gateway import LLMGatewayError, LLMOperation, LLMRequest
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


if __name__ == "__main__":
    unittest.main()
