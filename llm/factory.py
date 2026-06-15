from __future__ import annotations

from core.config import OpenAIConfig
from llm.gateway import LLMGateway
from llm.openai_client import OpenAIClientConfig, OpenAIResponsesClient


def build_openai_gateway(config: OpenAIConfig) -> LLMGateway:
    return LLMGateway(
        OpenAIResponsesClient(
            OpenAIClientConfig(
                api_key=config.api_key,
                model=config.model,
                timeout_s=config.timeout_s,
            )
        )
    )
