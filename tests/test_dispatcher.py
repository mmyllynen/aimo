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
        self.assertEqual(len(events), 2)

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
            options={"apua": True},
        )
        event = slash_to_event(slash)

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertTrue(all(message.kind == OutgoingKind.EPHEMERAL_TEXT for message in result.messages))

    def test_slash_aimo_help_takes_priority_over_attachment_ingest(self) -> None:
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="aimo",
            options={"apua": True},
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

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(len(result.messages), 5)

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
        self.assertEqual(payload["debug_trace"]["events"][0]["stage"], "route")

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
