from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from adapters.discord.attachments import AttachmentTooLargeError
from app.runtime import build_application_context
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage
from llm.openai_client import OpenAIResponsesClient


class ApplicationRuntimeTests(unittest.TestCase):
    def test_build_application_context_wires_dispatch_dependencies_without_llm_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _config(
                tmpdir,
                [
                    "[bot]",
                    "language = en",
                    "[storage]",
                    f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                    "[admin]",
                    "user_ids = admin-1",
                    "[limits]",
                    "max_attachment_size_bytes = 1234",
                ],
            )
            context = build_application_context(config_path)
            try:
                dispatch_context = context.dispatch_context()
                self.assertEqual(context.runtime.config.bot.language, SupportedLanguage.EN)
                self.assertTrue(context.admin_policy.is_admin("admin-1"))
                self.assertIsNone(context.llm_gateway)
                self.assertEqual(dispatch_context.language, SupportedLanguage.EN)
                self.assertEqual(dispatch_context.max_attachment_size_bytes, 1234)
                self.assertEqual(dispatch_context.raw_gpx_path, Path("data/raw_gpx"))
                self.assertEqual(dispatch_context.artifact_path, Path("artifacts"))
                result = context.dispatcher.dispatch(_message(), dispatch_context)
                self.assertEqual(result.status.value, "noop")
            finally:
                context.close()

    def test_build_application_context_builds_openai_gateway_when_key_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _config(
                tmpdir,
                [
                    "[openai]",
                    "api_key = test-key",
                    "model = gpt-test",
                    "[storage]",
                    f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                ],
            )
            context = build_application_context(config_path)
            try:
                self.assertIsInstance(context.llm_gateway.client, OpenAIResponsesClient)
                self.assertEqual(context.llm_gateway.client.config.api_key, "test-key")
                self.assertEqual(context.llm_gateway.client.config.model, "gpt-test")
            finally:
                context.close()

    def test_build_application_context_can_disable_llm_even_with_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _config(
                tmpdir,
                [
                    "[openai]",
                    "api_key = test-key",
                    "model = gpt-test",
                    "[storage]",
                    f"database_path = {Path(tmpdir) / 'nested' / 'aimo.sqlite3'}",
                ],
            )
            context = build_application_context(config_path, enable_llm=False)
            try:
                self.assertIsNone(context.llm_gateway)
                self.assertTrue((Path(tmpdir) / "nested").is_dir())
            finally:
                context.close()

    def test_application_context_hydrates_attachments_with_configured_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _config(
                tmpdir,
                [
                    "[storage]",
                    f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                    "[limits]",
                    "max_attachment_size_bytes = 10",
                ],
            )
            context = build_application_context(config_path)
            try:
                with self.assertRaises(AttachmentTooLargeError):
                    context.hydrate_attachments(
                        _message(
                            attachments=(
                                AttachmentRef(
                                    attachment_id="attachment-1",
                                    filename="run.gpx",
                                    content_type="application/gpx+xml",
                                    size_bytes=11,
                                    url="https://example.test/run.gpx",
                                ),
                            )
                        )
                    )
            finally:
                context.close()


def _config(tmpdir: str, lines: list[str]) -> Path:
    path = Path(tmpdir) / "aimo.conf"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _message(attachments: tuple[AttachmentRef, ...] = ()) -> CanonicalEvent:
    return CanonicalEvent(
        event_id="event-1",
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MESSAGE,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text="not for aimo",
        attachments=attachments,
    )


if __name__ == "__main__":
    unittest.main()
