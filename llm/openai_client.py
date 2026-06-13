from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from llm.gateway import LLMClient, LLMGatewayError, LLMRequest, LLMResponse


JsonObject = dict[str, Any]
UrlOpener = Callable[..., Any]


@dataclass(frozen=True)
class OpenAIClientConfig:
    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_s: float = 30.0


class OpenAIResponsesClient(LLMClient):
    def __init__(self, config: OpenAIClientConfig, *, opener: UrlOpener = urlopen) -> None:
        if not config.api_key:
            raise LLMGatewayError("OpenAI API key is required")
        if not config.model:
            raise LLMGatewayError("OpenAI model is required")
        self.config = config
        self.opener = opener

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        body = _request_body(request, model=self.config.model)
        http_request = Request(
            f"{self.config.base_url.rstrip('/')}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(http_request, timeout=self.config.timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            raise LLMGatewayError(f"OpenAI request failed: {exc}") from exc
        output_text = _output_text(payload)
        try:
            return LLMResponse(payload=json.loads(output_text), raw_text=output_text)
        except json.JSONDecodeError as exc:
            raise LLMGatewayError("OpenAI response did not contain valid JSON text") from exc


def _request_body(request: LLMRequest, *, model: str) -> JsonObject:
    return {
        "model": model,
        "instructions": request.system_prompt,
        "input": json.dumps(
            {
                "operation": request.operation.value,
                "payload": request.user_payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "max_output_tokens": request.max_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": _schema_name(request.operation.value),
                "schema": _json_schema(request.response_schema),
            }
        },
    }


def _json_schema(schema: JsonObject) -> JsonObject:
    return {
        "type": "object",
        "required": list(schema.get("required", ())),
        "additionalProperties": True,
        "properties": {
            key: _property_schema(property_schema)
            for key, property_schema in schema.get("properties", {}).items()
            if isinstance(property_schema, dict)
        },
    }


def _property_schema(schema: JsonObject) -> JsonObject:
    expected_type = schema.get("type")
    result: JsonObject = {}
    if expected_type is not None:
        result["type"] = expected_type
    if expected_type == "array":
        result["items"] = {}
    if expected_type == "object":
        result["additionalProperties"] = True
    if "enum" in schema:
        result["enum"] = schema["enum"]
    return result or {}


def _schema_name(operation: str) -> str:
    safe = "".join(character if character.isalnum() or character in "_-" else "_" for character in operation)
    return f"aimo_{safe}"[:64]


def _output_text(payload: JsonObject) -> str:
    if payload.get("status") not in {None, "completed"}:
        raise LLMGatewayError(f"OpenAI response status was {payload.get('status')!r}")
    if isinstance(payload.get("error"), dict) and payload["error"]:
        message = payload["error"].get("message", "OpenAI response error")
        raise LLMGatewayError(str(message))
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    for item in payload.get("output", ()):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", ()):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    raise LLMGatewayError("OpenAI response did not contain output_text")
