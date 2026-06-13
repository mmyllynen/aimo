from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import ConfigError, load_app_config
from core.i18n import SupportedLanguage, TranslationKey
from core.runtime import build_runtime


class ConfigRuntimeTests(unittest.TestCase):
    def test_missing_config_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_app_config(Path(tmpdir) / "missing.conf")

        self.assertEqual(config.bot.language, SupportedLanguage.FI)
        self.assertEqual(config.openai.model, "gpt-5.5")
        self.assertEqual(config.openai.max_tokens, 500)
        self.assertEqual(config.history.retention_days, 365)

    def test_reads_full_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "aimo.conf"
            path.write_text(
                "\n".join(
                    [
                        "[bot]",
                        "language = en",
                        "enabled = false",
                        "[discord]",
                        "token = discord-token",
                        "[openai]",
                        "api_key = openai-key",
                        "model = test-model",
                        "max_tokens = 123",
                        "[storage]",
                        "database_path = data/test.sqlite3",
                        "artifact_path = out/artifacts",
                        "raw_gpx_path = out/gpx",
                        "[admin]",
                        "user_ids = 111, 222",
                        "[limits]",
                        "max_attachment_size_bytes = 4096",
                        "[history]",
                        "retention_days = 30",
                        "[debug]",
                        "enabled = false",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_app_config(path)

        self.assertEqual(config.bot.language, SupportedLanguage.EN)
        self.assertFalse(config.bot.enabled)
        self.assertEqual(config.discord.token, "discord-token")
        self.assertEqual(config.openai.api_key, "openai-key")
        self.assertEqual(config.openai.model, "test-model")
        self.assertEqual(config.openai.max_tokens, 123)
        self.assertEqual(config.storage.database_path, Path("data/test.sqlite3"))
        self.assertEqual(config.admin.user_ids, frozenset({"111", "222"}))
        self.assertEqual(config.limits.max_attachment_size_bytes, 4096)
        self.assertEqual(config.history.retention_days, 30)
        self.assertFalse(config.debug.enabled)

    def test_require_secrets_rejects_missing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ConfigError):
                load_app_config(Path(tmpdir) / "missing.conf", require_secrets=True)

    def test_invalid_numeric_value_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "aimo.conf"
            path.write_text("[openai]\nmax_tokens = nope\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_app_config(path)

    def test_runtime_builds_translator_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "aimo.conf"
            path.write_text("[bot]\nlanguage = en\n", encoding="utf-8")

            runtime = build_runtime(path)

        self.assertEqual(runtime.config.bot.language, SupportedLanguage.EN)
        self.assertEqual(
            runtime.translator.text(TranslationKey.ERROR_UNEXPECTED),
            "An unexpected error occurred.",
        )


if __name__ == "__main__":
    unittest.main()
