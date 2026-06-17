from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from adapters.discord.commands import register_command_specs
from adapters.discord.normalization import DiscordSlashSnapshot, DiscordUserSnapshot, slash_to_event
from app.dispatcher import DispatchContext, Dispatcher
from core.config import ConfigError, load_app_config
from core.events import CanonicalEvent, EventKind, EventSource
from core.workflows import WorkflowStatus
from storage.unit_of_work import UnitOfWork, open_database


class SmokeError(RuntimeError):
    pass


class FakeCommandTree:
    def __init__(self) -> None:
        self.specs = []
        self.synced = False

    def add_command_spec(self, spec, *, guild=None) -> None:
        self.specs.append((spec, guild))

    async def sync(self, *, guild=None):
        self.synced = True
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Aimo production smoke checks without live OpenAI calls.")
    parser.add_argument("--config", default="aimo.conf", help="Config file to validate.")
    parser.add_argument("--log", default="logs/bot.log", help="Optional bot log file for health inspection.")
    args = parser.parse_args(argv)
    checks: list[tuple[str, str]] = []
    try:
        config = load_app_config(args.config, require_secrets=False)
        checks.append(("config", f"language={config.bot.language.value}"))
        _check_command_registration()
        checks.append(("commands", "slash command specs register"))
        _check_dispatch_paths()
        checks.append(("dispatch", "mention and slash paths dispatch"))
        _check_log(Path(args.log))
        checks.append(("log", "recent log has no startup traceback/error"))
    except (ConfigError, SmokeError, OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    for name, message in checks:
        print(f"OK {name}: {message}")
    return 0


def _check_command_registration() -> None:
    tree = FakeCommandTree()
    asyncio.run(register_command_specs(tree, guild=SimpleNamespace(id="guild-1")))
    names = {spec.name for spec, _guild in tree.specs}
    required = {"aimo", "treenit", "debug"}
    if not tree.synced or not required.issubset(names):
        raise SmokeError("slash command registration did not include required commands")


def _check_dispatch_paths() -> None:
    dispatcher = Dispatcher()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "aimo-smoke.sqlite3"
        connection = open_database(db_path, apply_migrations=True)
        try:
            mention = CanonicalEvent(
                event_id="smoke-mention",
                source=EventSource.DISCORD_MESSAGE,
                kind=EventKind.MENTION,
                guild_id="guild-1",
                channel_id="channel-1",
                user_id="user-1",
                user_name="runner",
                text="apua",
            )
            mention_result = dispatcher.dispatch(mention, DispatchContext(UnitOfWork(connection)))
            if mention_result.status != WorkflowStatus.SUCCESS:
                raise SmokeError(f"mention dispatch failed: {mention_result.status.value}")
            slash = slash_to_event(
                DiscordSlashSnapshot(
                    interaction_id="smoke-slash",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    user=DiscordUserSnapshot(user_id="user-1", user_name="runner"),
                    command_name="treenit",
                    subcommand="listaa",
                    options={},
                )
            )
            slash_result = dispatcher.dispatch(slash, DispatchContext(UnitOfWork(connection)))
            if slash_result.status != WorkflowStatus.SUCCESS:
                raise SmokeError(f"slash dispatch failed: {slash_result.status.value}")
        finally:
            connection.close()


def _check_log(path: Path) -> None:
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
    last_start = 0
    for index, line in enumerate(lines):
        if "Starting Aimo Discord runtime" in line:
            last_start = index
    recent = lines[last_start:]
    severe = [line for line in recent if "Traceback " in line or " CRITICAL " in line or " ERROR " in line]
    if severe:
        raise SmokeError(f"recent log contains errors after latest startup: {severe[-1]}")


if __name__ == "__main__":
    raise SystemExit(main())
