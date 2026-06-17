from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from adapters.discord.runtime import _register_real_app_commands
from app.runtime import build_application_context


class FakeCommandTree:
    def __init__(self) -> None:
        self.added: list[tuple[str, str | None]] = []

    def add_command(self, command, *, guild=None) -> None:
        guild_id = None if guild is None else str(guild.id)
        self.added.append((command.name, guild_id))


class FakeDiscordModule:
    Attachment = object
    Interaction = object

    class Object:
        def __init__(self, *, id: int) -> None:
            self.id = id

    class app_commands:
        Group = SimpleNamespace

        @staticmethod
        def command(*, name: str, description: str):
            def decorator(fn):
                return SimpleNamespace(name=name, description=description, callback=fn)

            return decorator

        @staticmethod
        def describe(**_kwargs):
            def decorator(fn):
                return fn

            return decorator


class FakeGroup:
    def __init__(self, *, name: str, description: str) -> None:
        self.name = name
        self.description = description

    def command(self, *, name: str, description: str):
        def decorator(fn):
            return SimpleNamespace(name=name, description=description, callback=fn, parent=self)

        return decorator


FakeDiscordModule.app_commands.Group = FakeGroup


class DiscordRealCommandRegistrationTests(unittest.TestCase):
    def test_guild_allowlist_also_registers_global_fallback_commands_locally(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "aimo.conf"
            config.write_text(
                "\n".join(
                    [
                        "[discord]",
                        "token = token",
                        "allowed_guild_ids = 111,222",
                        "[openai]",
                        "api_key = key",
                        "[storage]",
                        f"database_path = {Path(tmpdir) / 'aimo.sqlite3'}",
                    ]
                ),
                encoding="utf-8",
            )
            context = build_application_context(config)
            try:
                tree = FakeCommandTree()

                _register_real_app_commands(tree, context, discord_module=FakeDiscordModule)

                self.assertIn(("aimo", None), tree.added)
                self.assertIn(("treenit", None), tree.added)
                self.assertIn(("debug", None), tree.added)
                self.assertIn(("aimo", "111"), tree.added)
                self.assertIn(("aimo", "222"), tree.added)
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
