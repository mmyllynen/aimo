from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from adapters.discord.runtime import DiscordRuntimeError, build_discord_runtime, handle_interaction, handle_message, send_outbound
from adapters.discord.outgoing import DiscordOutbound
from app.runtime import build_application_context


class FakeChannel:
    def __init__(self) -> None:
        self.sent = []
        self.id = "channel-1"

    async def send(self, **kwargs):
        self.sent.append(kwargs)


class FakeResponse:
    def __init__(self) -> None:
        self.sent = []
        self.done = False

    def is_done(self) -> bool:
        return self.done

    async def send_message(self, **kwargs) -> None:
        self.sent.append(kwargs)
        self.done = True


class FakeFollowup:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, **kwargs) -> None:
        self.sent.append(kwargs)


class FakeCommandTree:
    def __init__(self) -> None:
        self.added = []
        self.synced = []

    def add_command_spec(self, spec, *, guild=None) -> None:
        self.added.append(spec.name)

    async def sync(self, *, guild=None) -> None:
        self.synced.append(guild)


class FakeDiscordModule:
    class File:
        def __init__(self, fp, *, filename: str) -> None:
            self.fp = fp
            self.filename = filename

    class Intents:
        def __init__(self) -> None:
            self.message_content = False

        @classmethod
        def default(cls):
            return cls()

    class Client:
        def __init__(self, *, intents) -> None:
            self.intents = intents
            self.events = {}
            self.user = SimpleNamespace(id="bot-1")
            self.started_with = ""
            self.tree = FakeCommandTree()

        def event(self, fn):
            self.events[fn.__name__] = fn
            return fn

        async def start(self, token: str) -> None:
            self.started_with = token


class DiscordRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_message_normalizes_dispatches_and_sends_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _context(tmpdir)
            try:
                channel = FakeChannel()
                message = SimpleNamespace(
                    id="message-1",
                    guild=SimpleNamespace(id="guild-1"),
                    channel=channel,
                    author=SimpleNamespace(id="user-1", name="runner", display_name="Runner", bot=False),
                    content="<@bot-1> apua",
                    created_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
                    attachments=(),
                    mentions=(SimpleNamespace(id="bot-1"),),
                )

                await handle_message(message, context, bot_user_id="bot-1", discord_module=FakeDiscordModule)

                self.assertEqual(len(channel.sent), 5)
                self.assertIn("GPX", channel.sent[1]["content"])
                self.assertEqual(channel.sent[0]["allowed_mentions"], {"parse": []})
            finally:
                context.close()

    async def test_handle_message_ignores_bot_authors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _context(tmpdir)
            try:
                channel = FakeChannel()
                message = SimpleNamespace(
                    id="message-1",
                    guild=None,
                    channel=channel,
                    author=SimpleNamespace(id="bot-2", name="other-bot", display_name="", bot=True),
                    content="<@bot-1> apua",
                    created_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
                    attachments=(),
                    mentions=(SimpleNamespace(id="bot-1"),),
                )

                await handle_message(message, context, bot_user_id="bot-1", discord_module=FakeDiscordModule)

                self.assertEqual(channel.sent, [])
            finally:
                context.close()

    async def test_send_outbound_sends_file_payload(self) -> None:
        channel = FakeChannel()
        outbound = DiscordOutbound(text="chart", filename="chart.png", content_type="image/png", content=b"png")

        await send_outbound(channel, outbound, discord_module=FakeDiscordModule)

        self.assertEqual(channel.sent[0]["content"], "chart")
        self.assertEqual(channel.sent[0]["file"].filename, "chart.png")
        self.assertEqual(channel.sent[0]["file"].fp.read(), b"png")

    async def test_handle_interaction_extracts_namespace_options_and_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _context(tmpdir)
            try:
                response = FakeResponse()
                followup = FakeFollowup()
                attachment = SimpleNamespace(
                    id="attachment-1",
                    filename="run.gpx",
                    content_type="application/gpx+xml",
                    size=10,
                    url="",
                )
                interaction = SimpleNamespace(
                    id="interaction-1",
                    guild=SimpleNamespace(id="guild-1"),
                    channel=SimpleNamespace(id="channel-1"),
                    user=SimpleNamespace(id="user-1", name="runner", display_name="Runner"),
                    command=SimpleNamespace(name="aimo"),
                    namespace=SimpleNamespace(apua=True, syote="", liite=attachment),
                    created_at=datetime(2026, 6, 13, tzinfo=timezone.utc),
                    response=response,
                    followup=followup,
                )

                await handle_interaction(interaction, context, discord_module=FakeDiscordModule)

                self.assertEqual(len(response.sent), 1)
                self.assertTrue(response.sent[0]["ephemeral"])
                self.assertIn("jutella", response.sent[0]["content"])
                self.assertEqual(len(followup.sent), 4)
            finally:
                context.close()

    async def test_build_discord_runtime_registers_events_and_starts_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _context(tmpdir, token="discord-token")
            try:
                runtime = build_discord_runtime(context, discord_module=FakeDiscordModule)

                self.assertIn("on_ready", runtime.client.events)
                self.assertIn("on_message", runtime.client.events)
                self.assertTrue(runtime.client.intents.message_content)
                await runtime.sync_commands(guild="guild-1")
                self.assertEqual(runtime.client.tree.added, ["aimo", "treenit", "debug"])
                self.assertEqual(runtime.client.tree.synced, ["guild-1"])
                await runtime.start()
                self.assertEqual(runtime.client.started_with, "discord-token")
            finally:
                context.close()

    async def test_runtime_start_requires_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = _context(tmpdir)
            try:
                runtime = build_discord_runtime(context, discord_module=FakeDiscordModule)

                with self.assertRaises(DiscordRuntimeError):
                    await runtime.start()
            finally:
                context.close()


def _context(tmpdir: str, *, token: str = ""):
    config = Path(tmpdir) / "aimo.conf"
    config.write_text(
        "\n".join(
            [
                "[discord]",
                f"token = {token}",
                "[storage]",
                f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                f"artifact_path = {Path(tmpdir) / 'artifacts'}",
                f"raw_gpx_path = {Path(tmpdir) / 'raw_gpx'}",
            ]
        ),
        encoding="utf-8",
    )
    return build_application_context(config, enable_llm=False)


if __name__ == "__main__":
    unittest.main()
