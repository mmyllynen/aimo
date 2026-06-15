from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from core.routing import WorkflowTarget


class TraceLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TraceStage(StrEnum):
    INBOUND = "inbound"
    REPOSITORY = "repository"
    ROUTE = "route"
    WORKFLOW = "workflow"
    LLM = "llm"
    RENDER = "render"
    OUTBOUND = "outbound"
    RESULT = "result"


@dataclass(frozen=True)
class TraceEvent:
    trace_id: str
    event_id: str
    workflow: WorkflowTarget | None
    stage: TraceStage | str
    level: TraceLevel
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
