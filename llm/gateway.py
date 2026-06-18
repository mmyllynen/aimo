from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol


JsonObject = dict[str, Any]


class LLMOperation(StrEnum):
    INTENT_CLASSIFICATION = "intent_classification"
    GPX_TITLE_EXTRACTION = "gpx_title_extraction"
    WORKOUT_REFERENCE_EXTRACTION = "workout_reference_extraction"
    PERIOD_REQUEST_INTERPRETATION = "period_request_interpretation"
    PERIOD_ANALYSIS_REPLY = "period_analysis_reply"
    CHAT_REPLY = "chat_reply"
    WORKOUT_REPLY = "workout_reply"
    VISUALIZATION_INTENT = "visualization_intent"
    VISUALIZATION_INTENT_REVISION = "visualization_intent_revision"
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


@dataclass(frozen=True)
class LLMCallTrace:
    operation: LLMOperation
    status: str
    duration_ms: float
    max_tokens: int
    response_keys: tuple[str, ...] = ()
    error_type: str = ""
    error_message: str = ""


class LLMClient(Protocol):
    def complete_json(self, request: LLMRequest) -> LLMResponse:
        pass


class LLMTraceObserver(Protocol):
    def __call__(self, trace: LLMCallTrace) -> None:
        pass


class LLMGateway:
    def __init__(self, client: LLMClient, *, observer: LLMTraceObserver | None = None) -> None:
        self.client = client
        self.observer = observer

    def run(self, request: LLMRequest) -> JsonObject:
        started = perf_counter()
        response_keys: tuple[str, ...] = ()
        status = "success"
        error_type = ""
        error_message = ""
        try:
            validate_request(request)
            response = self.client.complete_json(request)
            validate_schema(response.payload, request.response_schema)
            response_keys = tuple(sorted(response.payload.keys()))
            return response.payload
        except Exception as exc:
            status = "error"
            error_type = type(exc).__name__
            error_message = str(exc)[:500]
            raise
        finally:
            self._observe(
                LLMCallTrace(
                    operation=request.operation,
                    status=status,
                    duration_ms=(perf_counter() - started) * 1000,
                    max_tokens=request.max_tokens,
                    response_keys=response_keys,
                    error_type=error_type,
                    error_message=error_message,
                )
            )

    def _observe(self, trace: LLMCallTrace) -> None:
        if self.observer is None:
            return
        try:
            self.observer(trace)
        except Exception:
            pass


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
