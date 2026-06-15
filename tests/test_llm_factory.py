from __future__ import annotations

import unittest

from core.config import OpenAIConfig
from llm.factory import build_openai_gateway
from llm.openai_client import OpenAIResponsesClient


class LLMFactoryTests(unittest.TestCase):
    def test_build_openai_gateway_uses_configured_api_key_and_model(self) -> None:
        gateway = build_openai_gateway(OpenAIConfig(api_key="test-key", model="gpt-test", timeout_s=42.0))

        self.assertIsInstance(gateway.client, OpenAIResponsesClient)
        self.assertEqual(gateway.client.config.api_key, "test-key")
        self.assertEqual(gateway.client.config.model, "gpt-test")
        self.assertEqual(gateway.client.config.timeout_s, 42.0)


if __name__ == "__main__":
    unittest.main()
