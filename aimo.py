from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
from pathlib import Path

from adapters.discord.runtime import DiscordRuntimeError, build_discord_runtime
from app.preflight import run_production_preflight
from app.runtime import build_application_context
from core.config import ConfigError
from core.runtime import build_runtime
from storage.importer import ImportValidationError, import_json_file
from storage.sqlite import StorageError
from storage.unit_of_work import open_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aimo runtime bootstrap")
    parser.add_argument("--config", default="aimo.conf", help="Path to aimo.conf")
    parser.add_argument(
        "--require-secrets",
        action="store_true",
        help="Require production secrets such as Discord and OpenAI credentials",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate runtime configuration without starting integrations",
    )
    parser.add_argument(
        "--check-services",
        action="store_true",
        help="Validate configuration, storage schema, and service wiring without starting integrations",
    )
    parser.add_argument(
        "--run-discord",
        action="store_true",
        help="Start the Discord runtime; implies production secret validation",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Run production readiness checks without connecting to Discord or OpenAI",
    )
    parser.add_argument(
        "--allow-missing-discord-package",
        action="store_true",
        help="Allow production preflight to pass without discord.py installed; intended for local CI only",
    )
    parser.add_argument(
        "--import-data",
        help="Import documented Aimo JSON export data into the configured SQLite database",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate an import without committing database changes",
    )
    args = parser.parse_args(argv)
    _configure_logging()

    if args.preflight:
        report = run_production_preflight(
            Path(args.config),
            require_discord_package=not args.allow_missing_discord_package,
        )
        stream = sys.stdout if report.ok else sys.stderr
        print(report.summary(), file=stream)
        for check in report.checks:
            marker = "OK" if check.ok else "FAIL"
            print(f"[{marker}] {check.name}: {check.message}", file=stream)
        return 0 if report.ok else 2

    try:
        runtime = build_runtime(Path(args.config), require_secrets=args.require_secrets or args.run_discord)
    except (ConfigError, DiscordRuntimeError) as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Startup validation error: {exc}", file=sys.stderr)
        return 2

    if args.import_data:
        _ensure_parent_dir(runtime.config.storage.database_path)
        connection = open_database(runtime.config.storage.database_path, apply_migrations=True)
        try:
            report = import_json_file(connection, args.import_data, dry_run=args.dry_run)
        except (ImportValidationError, StorageError, OSError, ValueError, sqlite3.DatabaseError) as exc:
            print(f"Import error: {exc}", file=sys.stderr)
            return 2
        finally:
            connection.close()
        print(report.summary())
        for warning in report.warnings:
            print(f"WARNING: {warning}")
        return 0

    if args.check_services:
        context = build_application_context(Path(args.config), require_secrets=args.require_secrets)
        try:
            language = context.runtime.config.bot.language.value
            llm = "enabled" if context.llm_gateway is not None else "disabled"
            print(f"Aimo services OK: language={language} llm={llm}")
        finally:
            context.close()
        return 0

    if args.check:
        language = runtime.config.bot.language.value
        print(f"Aimo config OK: language={language}")
        return 0

    try:
        context = build_application_context(Path(args.config), require_secrets=args.require_secrets or args.run_discord)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    if args.run_discord:
        try:
            logging.getLogger(__name__).info("Starting Aimo Discord runtime.")
            asyncio.run(build_discord_runtime(context).start())
        except (ConfigError, DiscordRuntimeError) as exc:
            print(f"Startup validation error: {exc}", file=sys.stderr)
            return 2
        finally:
            context.close()
        return 0
    context.close()
    print("Aimo application services are valid; use --run-discord to start Discord.")
    return 0


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
