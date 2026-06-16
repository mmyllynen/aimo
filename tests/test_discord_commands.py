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

        self.assertEqual(set(specs), {"aimo", "treenit", "debug"})
        self.assertEqual(
            {option.name for option in specs["aimo"].options},
            {"syote", "liite"},
        )
        self.assertEqual(specs["aimo"].options[1].option_type, DiscordCommandOptionType.ATTACHMENT)
        subcommands = {subcommand.name: subcommand for subcommand in specs["treenit"].subcommands}
        self.assertEqual(
            set(subcommands),
            {"listaa", "nayta", "aktiivinen", "aseta_aktiivinen", "poista", "sykerajat", "aseta_sykerajat"},
        )
        self.assertEqual(specs["treenit"].options, ())
        self.assertEqual({option.name for option in subcommands["poista"].options}, {"viite"})
        self.assertEqual({option.name for option in subcommands["aseta_sykerajat"].options}, {"zones"})

    async def test_register_command_specs_adds_all_specs_and_syncs(self) -> None:
        tree = FakeCommandTree()
        guild = object()

        await register_command_specs(tree, guild=guild)

        self.assertEqual([item[0].name for item in tree.added], [spec.name for spec in COMMAND_SPECS])
        self.assertTrue(all(item[1] is guild for item in tree.added))
        self.assertEqual(tree.synced, [guild])


if __name__ == "__main__":
    unittest.main()
