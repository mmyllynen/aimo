from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.i18n import (
    CATALOGS,
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

    def test_help_topics_are_comprehensive_and_discord_sized(self) -> None:
        expected_fragments = {
            TranslationKey.HELP_COMMANDS: (
                "/treenit listaa",
                "/treenit poista",
                "/debug tila",
            ),
            TranslationKey.HELP_VISUALIZATION: (
                "+square",
                "+portrait",
                "+landscape",
                "+distance",
                "+duration",
                "+hr",
                "+maxhr",
                "+pace",
                "+ascent",
                "+date",
                "+social",
                "+somekuva",
            ),
            TranslationKey.HELP_SOCIAL_IMAGE: (
                "+classic",
                "+minimal",
                "+poster",
                "+routeonly",
                "+data",
                "+photo",
                "dim=0..70",
                "blur=0..20",
                "crop=center|top|bottom|left|right|X,Y",
                "route=default|auto|blue|white|black|red|green|yellow|#RRGGBB",
                "route_size=small|normal|large|huge",
                "title=top|bottom|hide",
                "stats=left|right|bottom|hide",
                "panel=dark|light|none",
                "font=clean|bold|mono|serif",
            ),
        }
        for catalog in CATALOGS.values():
            for key in (
                TranslationKey.HELP_INTRO,
                TranslationKey.HELP_COMMANDS,
                TranslationKey.HELP_VISUALIZATION,
                TranslationKey.HELP_SOCIAL_IMAGE,
                TranslationKey.HELP_PRIVACY,
                TranslationKey.HELP_UNKNOWN_TOPIC,
            ):
                self.assertLessEqual(len(catalog[key]), 2000)
            for key, fragments in expected_fragments.items():
                for fragment in fragments:
                    self.assertIn(fragment, catalog[key])

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
