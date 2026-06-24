from __future__ import annotations

import unittest

from adapters.discord.commands import COMMAND_SPECS, DiscordCommandOptionType, command_specs_by_name, register_command_specs


class FakeCommandTree:
    def __init__(self) -> None:
        self.added = []
        self.synced = []

    def add_command_spec(self, spec, *, guild=None) -> None:
        self.added.append((spec, guild))

    async def sync(self, *, guild=None) -> None:
        self.synced.append(guild)


class DiscordCommandSpecTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_specs_cover_required_surfaces(self) -> None:
        specs = command_specs_by_name()

        self.assertEqual(set(specs), {"aimo", "gpx", "help", "treenit", "asetukset", "debug"})
        self.assertEqual(
            {option.name for option in specs["aimo"].options},
            {"syote"},
        )
        gpx_subcommands = {subcommand.name: subcommand for subcommand in specs["gpx"].subcommands}
        self.assertEqual(set(gpx_subcommands), {"tallenna"})
        gpx_options = {option.name: option for option in gpx_subcommands["tallenna"].options}
        self.assertEqual(set(gpx_options), {"liite", "nimi"})
        self.assertEqual(gpx_options["liite"].option_type, DiscordCommandOptionType.ATTACHMENT)
        self.assertTrue(gpx_options["liite"].required)
        self.assertFalse(gpx_options["nimi"].required)
        self.assertEqual({option.name for option in specs["help"].options}, {"aihe"})
        self.assertEqual(specs["help"].options[0].choices, ("yleinen", "komennot", "visualisointi", "somekuva", "privacy"))
        subcommands = {subcommand.name: subcommand for subcommand in specs["treenit"].subcommands}
        self.assertEqual(
            set(subcommands),
            {
                "listaa",
                "nayta",
                "aktiivinen",
                "aseta_aktiivinen",
                "poista",
                "nimea",
                "tagaa",
                "poista_tagi",
            },
        )
        self.assertEqual(specs["treenit"].options, ())
        self.assertEqual({option.name for option in subcommands["poista"].options}, {"viite"})
        self.assertEqual({option.name for option in subcommands["nimea"].options}, {"viite", "nimi"})
        self.assertEqual({option.name for option in subcommands["tagaa"].options}, {"viite", "tagi"})
        self.assertEqual({option.name for option in subcommands["poista_tagi"].options}, {"viite", "tagi"})
        settings_subcommands = {subcommand.name: subcommand for subcommand in specs["asetukset"].subcommands}
        self.assertEqual(set(settings_subcommands), {"nayta", "sykerajat"})
        self.assertEqual({option.name for option in settings_subcommands["sykerajat"].options}, {"zones"})
        self.assertTrue(settings_subcommands["sykerajat"].options[0].required)
        self.assertEqual({option.name for option in specs["debug"].options}, {"level"})
        self.assertEqual(specs["debug"].options[0].choices, ("0", "1", "2"))

    async def test_register_command_specs_adds_all_specs_and_syncs(self) -> None:
        tree = FakeCommandTree()
        guild = object()

        await register_command_specs(tree, guild=guild)

        self.assertEqual([item[0].name for item in tree.added], [spec.name for spec in COMMAND_SPECS])
        self.assertTrue(all(item[1] is guild for item in tree.added))
        self.assertEqual(tree.synced, [guild])


if __name__ == "__main__":
    unittest.main()
