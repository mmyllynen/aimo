from __future__ import annotations

import unittest

from app.dispatcher import DispatchContext, Dispatcher
from core.events import CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.workflows import OutgoingKind, WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.unit_of_work import UnitOfWork, open_database


class ChatWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_mention_chat_uses_llm_and_persists_assistant_reply(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.CHAT_REPLY: {
                    "reply_text": "Tuo kuulostaa hyvältä suunnalta.",
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
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.TEXT)
        self.assertEqual(result.messages[0].text, "Tuo kuulostaa hyvältä suunnalta.")
        chat_request = next(request for request in client.requests if request.operation == LLMOperation.CHAT_REPLY)
        self.assertIn("Respond in fi", chat_request.system_prompt)
        self.assertEqual(chat_request.user_payload["user_text"], "mitä kuuluu?")
        capabilities = chat_request.user_payload["workflow_facts"]["capabilities"]
        self.assertEqual(capabilities["workout_management"]["list_command"], "/treenit toiminto:listaa")
        self.assertTrue(capabilities["workout_management"]["private_by_default"])
        self.assertIn("public chat", capabilities["workout_management"]["public_chat_behavior"])

        with UnitOfWork(self.connection) as repositories:
            history = repositories.history.list_recent_for_channel("channel-1")
        self.assertEqual([record.role for record in history], ["user", "assistant"])
        self.assertEqual(history[1].content, "Tuo kuulostaa hyvältä suunnalta.")

    def test_workout_management_like_mention_stays_generic_chat_with_capability_context(self) -> None:
        client = FakeLLMClient(
            {
                LLMOperation.CHAT_REPLY: {
                    "reply_text": "Treenien listaamiseen kannattaa käyttää /treenit toiminto:listaa.",
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
            text="listaa mun treenit",
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.FI,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        chat_requests = [request for request in client.requests if request.operation == LLMOperation.CHAT_REPLY]
        self.assertEqual(len(chat_requests), 1)
        self.assertEqual(chat_requests[0].user_payload["user_text"], "listaa mun treenit")
        self.assertEqual(
            chat_requests[0].user_payload["workflow_facts"]["capabilities"]["workout_management"]["list_command"],
            "/treenit toiminto:listaa",
        )

    def test_normal_message_is_only_persisted_and_does_not_call_llm(self) -> None:
        client = FakeLLMClient({})
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MESSAGE,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="kanavan yleinen viesti",
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.NOOP)
        self.assertEqual(client.requests, [])

    def test_mention_chat_without_gateway_returns_localized_model_error(self) -> None:
        event = CanonicalEvent(
            event_id="event-1",
            source=EventSource.DISCORD_MESSAGE,
            kind=EventKind.MENTION,
            guild_id="guild-1",
            channel_id="channel-1",
            user_id="user-1",
            user_name="runner",
            text="vastaa jotain",
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SYSTEM_ERROR)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_MODEL_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
