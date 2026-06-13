from __future__ import annotations

import json

from app.redaction import redact_payload
from core.events import CanonicalEvent
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from app.policy import AdminPolicy
from storage.unit_of_work import RepositoryBundle


class DebugWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        admin_policy: AdminPolicy,
        current_trace_id: str,
    ) -> WorkflowResult:
        latest = (
            repositories.debug_traces.latest(exclude_trace_id=current_trace_id)
            if admin_policy.is_admin(event.user_id)
            else repositories.debug_traces.latest_for_user(event.user_id, exclude_trace_id=current_trace_id)
        )
        if latest is None:
            payload = {"debug_trace": None}
        else:
            payload = {
                "debug_trace": {
                    "trace_id": latest.trace_id,
                    "source_event_id": latest.source_event_id,
                    "workflow": latest.workflow,
                    "status": latest.status,
                    "started_at": latest.started_at,
                    "finished_at": latest.finished_at,
                    "payload": redact_payload(latest.payload),
                    "events": [
                        {
                            "trace_event_id": trace_event.trace_event_id,
                            "stage": trace_event.stage,
                            "level": trace_event.level,
                            "message": trace_event.message,
                            "payload": redact_payload(trace_event.payload),
                            "created_at": trace_event.created_at,
                        }
                        for trace_event in repositories.debug_traces.list_events(latest.trace_id)
                    ],
                }
            }

        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.EPHEMERAL_FILE,
                    filename="aimo-debug.json",
                    content_type="application/json",
                    content=json.dumps(payload, sort_keys=True, indent=2).encode("utf-8"),
                ),
            ),
        )
