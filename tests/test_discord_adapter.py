from __future__ import annotations

import unittest

from adapters.discord.help import build_help_result
from adapters.discord.normalization import (
    DiscordAttachmentSnapshot,
    DiscordMessageSnapshot,
    DiscordSlashSnapshot,
    DiscordUserSnapshot,
    message_to_event,
    slash_to_event,
)
from adapters.discord.outgoing import OutboundCollector, outgoing_to_discord
from core.events import EventKind, EventSource
from core.i18n import SupportedLanguage, Translator
from core.workflows import OutgoingKind, OutgoingMessage


class DiscordAdapterTests(unittest.TestCase):
    def test_message_mention_normalizes_to_canonical_event_and_strips_bot_mention(self) -> None:
        message = DiscordMessageSnapshot(
            message_id="message-1",
            guild_id="guild-1",
            channel_id="channel-1",
            author=DiscordUserSnapshot(
                user_id="user-1",
                user_name="runner",
                display_name="Runner",
            ),
            content="<@bot-1> piirra viimeisin treeni",
            mentioned_user_ids=("bot-1",),
            attachments=(
                DiscordAttachmentSnapshot(
                    attachment_id="attachment-1",
                    filename="run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=123,
                    url="https://example.test/run.gpx",
                ),
            ),
        )

        event = message_to_event(message, bot_user_id="bot-1")

        self.assertEqual(event.source, EventSource.DISCORD_MESSAGE)
        self.assertEqual(event.kind, EventKind.MENTION)
        self.assertEqual(event.text, "piirra viimeisin treeni")
        self.assertEqual(event.user_id, "user-1")
        self.assertEqual(event.metadata["discord_display_name"], "Runner")
        self.assertTrue(event.metadata["mentioned_bot"])
        self.assertEqual(event.attachments[0].filename, "run.gpx")

    def test_non_mention_message_stays_normal_message(self) -> None:
        message = DiscordMessageSnapshot(
            message_id="message-1",
            guild_id=None,
            channel_id="channel-1",
            author=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            content="not for the bot",
        )

        event = message_to_event(message, bot_user_id="bot-1")

        self.assertEqual(event.kind, EventKind.MESSAGE)
        self.assertEqual(event.text, "not for the bot")
        self.assertFalse(event.metadata["mentioned_bot"])

    def test_slash_command_uses_syote_as_text_and_preserves_options(self) -> None:
        slash = DiscordSlashSnapshot(
            interaction_id="interaction-1",
            guild_id="guild-1",
            channel_id="channel-1",
            user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
            command_name="aimo",
            options={"syote": "apua", "apua": True},
        )

        event = slash_to_event(slash)

        self.assertEqual(event.source, EventSource.DISCORD_SLASH)
        self.assertEqual(event.kind, EventKind.SLASH_COMMAND)
        self.assertEqual(event.text, "apua")
        self.assertEqual(event.metadata["command_name"], "aimo")
        self.assertEqual(event.metadata["options"]["apua"], True)

    def test_outgoing_payload_renders_i18n_and_disables_mentions(self) -> None:
        message = OutgoingMessage(
            kind=OutgoingKind.EPHEMERAL_TEXT,
            text_key="error.no_matching_workout",
        )

        outbound = outgoing_to_discord(message, Translator(SupportedLanguage.EN))

        self.assertTrue(outbound.ephemeral)
        self.assertEqual(outbound.text, "I could not find a workout matching the request.")
        self.assertEqual(outbound.allowed_mentions, {"parse": []})

    def test_outgoing_payload_sanitizes_broad_mentions(self) -> None:
        message = OutgoingMessage(
            kind=OutgoingKind.TEXT,
            text="@everyone check this and @here too",
        )

        outbound = outgoing_to_discord(message, Translator())

        self.assertEqual(outbound.text, "@ everyone check this and @ here too")

    def test_help_result_can_be_rendered_and_sent_through_collector(self) -> None:
        result = build_help_result(ephemeral=True)
        collector = OutboundCollector()
        translator = Translator(SupportedLanguage.FI)

        for message in result.messages:
            collector.send(outgoing_to_discord(message, translator))

        self.assertEqual(len(collector.sent), 5)
        self.assertTrue(all(message.ephemeral for message in collector.sent))
        self.assertIn("GPX", collector.sent[1].text)


if __name__ == "__main__":
    unittest.main()

