from __future__ import annotations

from core.events import CanonicalEvent
from core.routing import RouteDecision
from core.workflows import WorkflowResult, WorkflowStatus


class NoopWorkflow:
    def handle(self, event: CanonicalEvent, route: RouteDecision) -> WorkflowResult:
        return WorkflowResult(status=WorkflowStatus.NOOP)

