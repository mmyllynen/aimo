from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkflowTarget(StrEnum):
    CHAT = "chat"
    WORKOUT_CHAT = "workout_chat"
    GPX_INGEST = "gpx_ingest"
    WORKOUT_MANAGEMENT = "workout_management"
    SETTINGS = "settings"
    VISUALIZATION = "visualization"
    DEBUG = "debug"
    HELP = "help"


class RouteConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class RouteDecision:
    target: WorkflowTarget
    confidence: RouteConfidence = RouteConfidence.MEDIUM
    slots: dict[str, Any] = field(default_factory=dict)
    clarification: str = ""
    reason: str = ""
