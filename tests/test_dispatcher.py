from __future__ import annotations

import json
import unittest
from dataclasses import replace

from adapters.discord.normalization import DiscordMessageSnapshot, DiscordSlashSnapshot, DiscordUserSnapshot, message_to_event, slash_to_event
from app.dispatcher import DispatchContext, Dispatcher
from app.policy import AdminPolicy
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource
from core.workflows import OutgoingKind, WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.repositories import DebugTraceEventRecord
from storage.unit_of_work import UnitOfWork, open_database


class DispatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_non_mention_message_is_persisted_and_noop(self) -> None:
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MESSAGE,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="not for Aimo",
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.NOOP)
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNotNone(repositories.users.get("user-1"))
            history = repositories.history.list_recent_for_channel("channel-1")
            trace = repositories.debug_traces.latest_for_user("user-1")
        self.assertEqual(history[0].content, "not for Aimo")
        self.assertEqual(trace.workflow, "chat")
        self.assertEqual(trace.status, "noop")

    def test_dispatcher_redacts_trace_slots_and_prunes_old_traces(self) -> None:
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_SLASH,
            kind=EventKind.SLASH_COMMAND,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="listaa",
            metadata={"command_name": "treenit", "options": {"toiminto": "listaa", "token": "secret-token"}},
        )

        self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection), trace_keep_limit=10))
        with UnitOfWork(self.connection) as repositories:
            first_trace = repositories.debug_traces.latest_for_user("user-1")
            first_events = repositories.debug_traces.list_events(first_trace.trace_id)
        route_event = next(event for event in first_events if event.stage == "route")
        self.assertEqual(route_event.payload["slots"]["options"]["token"], "[redacted]")
        repository_event = next(
            event
            for event in first_events
            if event.stage == "repository" and event.message == "workouts.list_for_user"
        )
        self.assertEqual(repository_event.payload["args"]["positional_types"], ["str"])
        self.assertNotIn("user-1", json.dumps(repository_event.payload))

        self.dispatcher.dispatch(
            CanonicalEvent(
                event_id="event-2",
                source=EventSource.DISCORD_MESSAGE,
                kind=EventKind.MESSAGE,
                guild_id="guild-1",
                channel_id="channel-1",
                user_id="user-1",
                user_name="runner",
                text="second",
            ),
            DispatchContext(UnitOfWork(self.connection), trace_keep_limit=1),
        )

        with UnitOfWork(self.connection) as repositories:
            latest = repositories.debug_traces.latest_for_user("user-1")
            events = repositories.debug_traces.list_events(latest.trace_id)
        self.assertEqual(latest.source_event_id, "event-2")
        self.assertGreaterEqual(len(events), 6)

    def test_dispatcher_records_observability_spans_for_request_lifecycle(self) -> None:
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="apua",
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            trace = repositories.debug_traces.latest_for_user("user-1")
            events = repositories.debug_traces.list_events(trace.trace_id)
        stages = [event.stage for event in events]
        for expected_stage in ("inbound", "repository", "route", "workflow", "outbound", "result"):
            self.assertIn(expected_stage, stages)
        inbound = next(event for event in events if event.stage == "inbound")
        self.assertEqual(inbound.payload["text_chars"], 4)
        self.assertNotIn("apua", json.dumps(inbound.payload))

    def test_dispatcher_records_llm_call_trace_event_without_prompt_payload(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.INTENT_CLASSIFICATION: {
                    "workflow": "chat",
                    "confidence": "high",
                    "slots": {},
                    "clarification": "",
                    "reason": "General chat.",
                },
                LLMOperation.CHAT_REPLY: {
                    "reply_text": "Moi.",
                    "tone": "concise",
                    "should_update_summary": False,
                }
            }
        )
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="mitä kuuluu?",
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            trace = repositories.debug_traces.latest_for_user("user-1")
            events = repositories.debug_traces.list_events(trace.trace_id)
        llm_event = next(event for event in events if event.stage == "llm" and event.message == "chat_reply")
        self.assertEqual(llm_event.message, "chat_reply")
        self.assertEqual(llm_event.payload["status"], "success")
        self.assertEqual(llm_event.payload["response_keys"], ["reply_text", "should_update_summary", "tone"])
        self.assertNotIn("user_text", llm_event.payload)
        self.assertNotIn("system_prompt", llm_event.payload)

    def test_llm_routing_can_route_mention_without_keyword_markers(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.INTENT_CLASSIFICATION: {
                    "workflow": "visualization",
                    "confidence": "high",
                    "slots": {"workout_selector": {"type": "latest"}},
                    "clarification": "",
                    "reason": "User wants a chart.",
                },
                LLMOperation.VISUALIZATION_INTENT: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["heart_rate_bpm"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                },
            }
        )
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="tee se sama juttu viimeisestä lenkistä",
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "no_matching_workout")
        self.assertEqual(client.requests[0].operation, LLMOperation.INTENT_CLASSIFICATION)
        self.assertEqual(client.requests[0].user_payload["user_text"], "tee se sama juttu viimeisestä lenkistä")
        self.assertNotIn("workout_points", client.requests[0].user_payload)

    def test_llm_routing_failure_falls_back_to_deterministic_chat_route(self) -> None:
        client = FakeLLMClient({})
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="mitä kuuluu?",
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SYSTEM_ERROR)
        with UnitOfWork(self.connection) as repositories:
            trace = repositories.debug_traces.latest_for_user("user-1")
        self.assertEqual(trace.workflow, "chat")

    def test_mention_help_routes_to_public_help(self) -> None:
        message = DiscordMessageSnapshot(
            message_id="event-1",
            guild_id="guild-1",
            channel_id="channel-1",
            author=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            content="<@bot-1> apua",
            mentioned_user_ids=("bot-1",),
        )
        event = message_to_event(message, bot_user_id="bot-1")

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(len(result.messages), 5)
        self.assertTrue(all(message.kind == OutgoingKind.TEXT for message in result.messages))

    def test_slash_aimo_help_routes_to_ephemeral_help(self) -> None:
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="aimo",
        )
        event = slash_to_event(slash)

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertTrue(all(message.kind == OutgoingKind.EPHEMERAL_TEXT for message in result.messages))

    def test_slash_aimo_attachment_routes_to_ingest_without_help_flag(self) -> None:
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="aimo",
            options={"liite": "attachment-1"},
        )
        event = slash_to_event(slash)
        event = replace(
            event,
            attachments=(
                AttachmentRef(
                    attachment_id="attachment-1",
                    filename="run.gpx",
                    content_type="application/gpx+xml",
                ),
            ),
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "unsupported_attachment")

    def test_debug_workflow_returns_requesters_latest_trace_as_json_file(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.debug_traces.create(
                trace_id="trace-1",
                source_event_id="event-0",
                workflow="help",
                status="success",
                started_at="2026-06-13T10:00:00Z",
                payload={"route": "help", "user_id": "user-1"},
            )
            repositories.debug_traces.add_event(
                DebugTraceEventRecord(
                    trace_event_id="trace-event-1",
                    trace_id="trace-1",
                    stage="route",
                    level="info",
                    message="routed",
                    created_at="2026-06-13T10:00:01Z",
                )
            )
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="debug",
        )

        result = self.dispatcher.dispatch(slash_to_event(slash), DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.EPHEMERAL_FILE)
        payload = json.loads(result.messages[0].content.decode("utf-8"))
        self.assertEqual(payload["debug_trace"]["trace_id"], "trace-1")
        self.assertEqual(payload["debug_trace"]["event_count"], 1)
        self.assertEqual(payload["debug_trace"]["events_truncated"], 0)
        self.assertEqual(payload["debug_trace"]["events"][0]["stage"], "route")

    def test_debug_workflow_limits_large_trace_export_and_redacts_payloads(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.debug_traces.create(
                trace_id="trace-1",
                source_event_id="event-0",
                workflow="chat",
                status="success",
                started_at="2026-06-13T10:00:00Z",
                payload={
                    "user_id": "user-1",
                    "token": "secret-token",
                    "long": "x" * 500,
                },
            )
            for index in range(105):
                repositories.debug_traces.add_event(
                    DebugTraceEventRecord(
                        trace_event_id=f"trace-event-{index:03d}",
                        trace_id="trace-1",
                        stage="repository",
                        level="info",
                        message="stored",
                        payload={"authorization": "Bearer secret", "items": list(range(30))},
                        created_at=f"2026-06-13T10:00:{index:02d}Z",
                    )
                )
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="debug",
        )

        result = self.dispatcher.dispatch(slash_to_event(slash), DispatchContext(UnitOfWork(self.connection)))
        payload = json.loads(result.messages[0].content.decode("utf-8"))
        trace = payload["debug_trace"]

        self.assertEqual(trace["event_count"], 105)
        self.assertEqual(trace["events_returned"], 100)
        self.assertEqual(trace["events_truncated"], 5)
        self.assertEqual(trace["payload"]["token"], "[redacted]")
        self.assertIn("[truncated]", trace["payload"]["long"])
        self.assertEqual(trace["events"][0]["payload"]["authorization"], "[redacted]")
        self.assertEqual(len(trace["events"][0]["payload"]["items"]), 21)

    def test_debug_workflow_does_not_return_other_users_trace_for_non_admin(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.debug_traces.create(
                trace_id="other-user-trace",
                source_event_id="event-0",
                workflow="help",
                status="success",
                started_at="2026-06-13T10:00:00Z",
                payload={"user_id": "user-2"},
            )
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="debug",
        )

        result = self.dispatcher.dispatch(slash_to_event(slash), DispatchContext(UnitOfWork(self.connection)))
        payload = json.loads(result.messages[0].content.decode("utf-8"))

        self.assertIsNone(payload["debug_trace"])

    def test_debug_workflow_returns_global_latest_for_admin(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.debug_traces.create(
                trace_id="other-user-trace",
                source_event_id="event-0",
                workflow="help",
                status="success",
                started_at="2026-06-13T10:00:00Z",
                payload={"user_id": "user-2"},
            )
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="admin-1", user_name="admin"),
            command_name="debug",
        )

        result = self.dispatcher.dispatch(
            slash_to_event(slash),
            DispatchContext(
                UnitOfWork(self.connection),
                admin_policy=AdminPolicy(frozenset({"admin-1"})),
            ),
        )
        payload = json.loads(result.messages[0].content.decode("utf-8"))

        self.assertEqual(payload["debug_trace"]["trace_id"], "other-user-trace")


if __name__ == "__main__":
    unittest.main()
