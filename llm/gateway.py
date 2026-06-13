from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


JsonObject = dict[str, Any]


class LLMOperation(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    WORKOUT_REFERENCE_EXTRACTION = "workout_reference_extraction"
    CHAT_REPLY = "chat_reply"
    WORKOUT_REPLY = "workout_reply"
    VISUALIZATION_INTENT = "visualization_intent"
    VISUALIZATION_PLAN = "visualization_plan"
    HISTORY_SUMMARY = "history_summary"


class LLMGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMRequest:
    operation: LLMOperation
    system_prompt: str
    user_payload: JsonObject
    response_schema: JsonObject
    max_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    payload: JsonObject
    raw_text: str = ""


class LLMClient(Protocol):
    def complete_json(self, request: LLMRequest) -> LLMResponse:
        pass


class LLMGateway:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def run(self, request: LLMRequest) -> JsonObject:
        validate_request(request)
        response = self.client.complete_json(request)
        validate_schema(response.payload, request.response_schema)
        return response.payload


class FakeLLMClient:
    def __init__(self, responses: dict[LLMOperation, JsonObject]) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if request.operation not in self.responses:
            raise LLMGatewayError(f"No fake response configured for {request.operation}")
        return LLMResponse(payload=self.responses[request.operation])


def validate_request(request: LLMRequest) -> None:
    if request.max_tokens <= 0:
        raise LLMGatewayError("max_tokens must be positive")
    _reject_forbidden_payload(request.user_payload)


def validate_schema(payload: JsonObject, schema: JsonObject) -> None:
    required = schema.get("required", ())
    properties = schema.get("properties", {})
    for key in required:
        if key not in payload:
            raise LLMGatewayError(f"Missing required model output field: {key}")
    for key, value in payload.items():
        if key not in properties:
            continue
        expected_type = properties[key].get("type")
        if expected_type is not None and not _matches_type(value, expected_type):
            raise LLMGatewayError(f"Invalid type for model output field: {key}")
        enum_values = properties[key].get("enum")
        if enum_values is not None and value not in enum_values:
            raise LLMGatewayError(f"Invalid enum value for model output field: {key}")


def _matches_type(value: Any, expected_type: str | list[str]) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(value, item) for item in expected_type)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _reject_forbidden_payload(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in {"raw_gpx", "gpx_xml", "workout_points", "point_rows", "raw_points"}:
                raise LLMGatewayError(f"Forbidden large/raw payload field for LLM input: {path}.{key}")
            _reject_forbidden_payload(item, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) > 100:
            raise LLMGatewayError(f"Payload list too large for LLM input: {path}")
        for index, item in enumerate(value):
            _reject_forbidden_payload(item, f"{path}[{index}]")

