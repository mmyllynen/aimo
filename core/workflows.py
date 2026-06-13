from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from v3.core.errors import AppError
from v3.core.trace import TraceEvent


class WorkflowStatus(StrEnum):
    SUCCESS = "success"
    CLARIFY = "clarify"
    USER_ERROR = "user_error"
    SYSTEM_ERROR = "system_error"
    FORBIDDEN = "forbidden"
    NOOP = "noop"


class OutgoingKind(StrEnum):
    TEXT = "text"
    FILE = "file"
    EPHEMERAL_TEXT = "ephemeral_text"
    EPHEMERAL_FILE = "ephemeral_file"


@dataclass(frozen=True)
class OutgoingMessage:
    kind: OutgoingKind
    text: str = ""
    filename: str = ""
    content_type: str = ""
    content: bytes | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StateUpdate:
    namespace: str
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    messages: tuple[OutgoingMessage, ...] = ()
    state_updates: tuple[StateUpdate, ...] = ()
    trace_events: tuple[TraceEvent, ...] = ()
    error: AppError | None = None

    @property
    def ok(self) -> bool:
        return self.status == WorkflowStatus.SUCCESS

