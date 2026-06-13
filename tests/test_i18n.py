from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.i18n import (
    DEFAULT_LANGUAGE,
    SupportedLanguage,
    TranslationKey,
    Translator,
    UnsupportedLanguageError,
    load_localization_config,
    validate_catalogs,
)


class I18nTests(unittest.TestCase):
    def test_catalogs_are_complete(self) -> None:
        validate_catalogs()

    def test_translator_renders_configured_language(self) -> None:
        translator = Translator(SupportedLanguage.EN)

        self.assertEqual(
            translator.text(TranslationKey.ERROR_NO_MATCHING_WORKOUT),
            "I could not find a workout matching the request.",
        )

    def test_translator_interpolates_values(self) -> None:
        translator = Translator(SupportedLanguage.FI)

        self.assertEqual(
            translator.text(TranslationKey.ERROR_MISSING_METRIC, metric="syke"),
            "Treenistä puuttuu tarvittava mittari: syke.",
        )

    def test_missing_config_defaults_to_finnish(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_localization_config(Path(tmpdir) / "missing.conf")

        self.assertEqual(config.language, DEFAULT_LANGUAGE)

    def test_reads_language_from_aimo_conf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "aimo.conf"
            path.write_text("[bot]\nlanguage = en\n", encoding="utf-8")

            config = load_localization_config(path)

        self.assertEqual(config.language, SupportedLanguage.EN)

    def test_rejects_unsupported_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "aimo.conf"
            path.write_text("[bot]\nlanguage = sv\n", encoding="utf-8")

            with self.assertRaises(UnsupportedLanguageError):
                load_localization_config(path)


if __name__ == "__main__":
    unittest.main()
