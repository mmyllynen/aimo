from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCategory(StrEnum):
    UNSUPPORTED_ATTACHMENT = "unsupported_attachment"
    INVALID_GPX = "invalid_gpx"
    NO_MATCHING_WORKOUT = "no_matching_workout"
    MISSING_METRIC = "missing_metric"
    AMBIGUOUS_WORKOUT = "ambiguous_workout"
    VISUALIZATION_PLAN_INVALID = "visualization_plan_invalid"
    RENDER_FAILED = "render_failed"
    MODEL_UNAVAILABLE = "model_unavailable"
    PERMISSION_DENIED = "permission_denied"
    STORAGE_ERROR = "storage_error"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class AppError:
    category: ErrorCategory
    message: str
    user_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

