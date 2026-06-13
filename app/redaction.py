from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
)


@dataclass(frozen=True)
class RedactionPolicy:
    max_string_length: int = 500
    max_sequence_items: int = 20
    max_mapping_items: int = 50
    max_depth: int = 4


DEFAULT_REDACTION_POLICY = RedactionPolicy()
REDACTED = "[redacted]"
TRUNCATED = "[truncated]"


def redact_payload(value: Any, policy: RedactionPolicy = DEFAULT_REDACTION_POLICY, *, _depth: int = 0) -> Any:
    if _depth >= policy.max_depth:
        return TRUNCATED
    if isinstance(value, Mapping):
        return _redact_mapping(value, policy, _depth=_depth)
    if isinstance(value, str):
        return _redact_string(value, policy)
    if isinstance(value, bytes):
        return f"[bytes:{len(value)}]"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _redact_sequence(value, policy, _depth=_depth)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)


def _redact_mapping(value: Mapping[Any, Any], policy: RedactionPolicy, *, _depth: int) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for index, (raw_key, raw_item) in enumerate(value.items()):
        if index >= policy.max_mapping_items:
            redacted[TRUNCATED] = f"{len(value) - policy.max_mapping_items} more keys"
            break
        key = str(raw_key)
        if _is_sensitive_key(key):
            redacted[key] = REDACTED
        else:
            redacted[key] = redact_payload(raw_item, policy, _depth=_depth + 1)
    return redacted


def _redact_sequence(value: Sequence[Any], policy: RedactionPolicy, *, _depth: int) -> list[Any]:
    items = [redact_payload(item, policy, _depth=_depth + 1) for item in value[: policy.max_sequence_items]]
    if len(value) > policy.max_sequence_items:
        items.append(f"{TRUNCATED}: {len(value) - policy.max_sequence_items} more items")
    return items


def _redact_string(value: str, policy: RedactionPolicy) -> str:
    if len(value) <= policy.max_string_length:
        return value
    return f"{value[: policy.max_string_length]}...{TRUNCATED}"


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)

