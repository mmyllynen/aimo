from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import timezone

from core.errors import AppError, ErrorCategory
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource
from core.i18n import LocalizedText, TranslationKey
from core.routing import RouteConfidence, RouteDecision, WorkflowTarget
from core.trace import TraceEvent, TraceLevel, TraceStage
from core.workflows import (
    OutgoingKind,
    OutgoingMessage,
    StateUpdate,
    WorkflowResult,
    WorkflowStatus,
)


class CoreContractTests(unittest.TestCase):
    def test_canonical_event_defaults_and_attachment_refs(self) -> None:
        attachment = AttachmentRef(
            attachment_id="att-1",
            filename="run.gpx",
            content_type="application/gpx+xml",
            size_bytes=123,
        )

        event = CanonicalEvent(
            event_id="evt-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="@Aimo hello",
            attachments=(attachment,),
        )

        self.assertEqual(event.attachments[0].filename, "run.gpx")
        self.assertEqual(event.metadata, {})
        self.assertEqual(event.created_at.tzinfo, timezone.utc)

        with self.assertRaises(FrozenInstanceError):
            event.text = "changed"  # type: ignore[misc]

    def test_route_decision_carries_bounded_slots(self) -> None:
        decision = RouteDecision(
            target=WorkflowTarget.VISUALIZATION,
            confidence=RouteConfidence.HIGH,
            slots={"workout_selector": "latest", "metric_names": ["heart_rate"]},
            reason="User asked for a chart.",
        )

        self.assertEqual(decision.target, WorkflowTarget.VISUALIZATION)
        self.assertEqual(decision.slots["workout_selector"], "latest")
        self.assertEqual(decision.clarification, "")

    def test_app_error_supports_localized_user_message_key(self) -> None:
        error = AppError(
            category=ErrorCategory.MISSING_METRIC,
            message="heart_rate stream missing",
            user_message_key=TranslationKey.ERROR_MISSING_METRIC.value,
            user_message_params={"metric": "heart_rate"},
            details={"workout_id": "w-1"},
        )

        self.assertEqual(error.category, ErrorCategory.MISSING_METRIC)
        self.assertEqual(error.user_message_params["metric"], "heart_rate")
        self.assertEqual(error.details["workout_id"], "w-1")

    def test_trace_event_defaults_to_utc_and_optional_workflow(self) -> None:
        trace = TraceEvent(
            trace_id="trace-1",
            event_id="evt-1",
            workflow=WorkflowTarget.CHAT,
            stage=TraceStage.ROUTE,
            level=TraceLevel.INFO,
            message="routed",
            payload={"confidence": "high"},
        )

        self.assertEqual(trace.workflow, WorkflowTarget.CHAT)
        self.assertEqual(trace.stage, TraceStage.ROUTE)
        self.assertEqual(trace.created_at.tzinfo, timezone.utc)
        self.assertEqual(trace.payload["confidence"], "high")

    def test_workflow_result_models_messages_state_trace_and_errors(self) -> None:
        message = OutgoingMessage(
            kind=OutgoingKind.TEXT,
            localized_text=LocalizedText(
                key=TranslationKey.WORKFLOW_ACCEPTED,
                params={},
            ),
        )
        update = StateUpdate(namespace="users", operation="touch", payload={"user_id": "user-1"})
        trace = TraceEvent(
            trace_id="trace-1",
            event_id="evt-1",
            workflow=WorkflowTarget.HELP,
            stage="reply",
            level=TraceLevel.DEBUG,
            message="reply created",
        )
        result = WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(message,),
            state_updates=(update,),
            trace_events=(trace,),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.WORKFLOW_ACCEPTED)
        self.assertEqual(result.state_updates[0].operation, "touch")

    def test_non_success_workflow_result_is_not_ok(self) -> None:
        result = WorkflowResult(
            status=WorkflowStatus.USER_ERROR,
            error=AppError(
                category=ErrorCategory.NO_MATCHING_WORKOUT,
                message="not found",
                user_message_key=TranslationKey.ERROR_NO_MATCHING_WORKOUT.value,
            ),
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.category, ErrorCategory.NO_MATCHING_WORKOUT)


if __name__ == "__main__":
    unittest.main()
