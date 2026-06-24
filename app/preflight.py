from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from app.runtime import ApplicationContext, build_application_context
from core.config import ConfigError
from core.i18n import validate_catalogs
from storage.files import write_bytes_under
from visualization.animation import _ffmpeg_executable


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def summary(self) -> str:
        status = "OK" if self.ok else "FAILED"
        passed = sum(1 for check in self.checks if check.ok)
        return f"Aimo production preflight {status}: {passed}/{len(self.checks)} checks passed"


def run_production_preflight(
    config_path: str | Path = "aimo.conf",
    *,
    require_discord_package: bool = True,
) -> PreflightReport:
    checks: list[PreflightCheck] = []
    context: ApplicationContext | None = None
    try:
        validate_catalogs()
        checks.append(_ok("i18n", "catalogs are complete"))
    except Exception as exc:
        checks.append(_fail("i18n", f"catalog validation failed: {type(exc).__name__}"))

    try:
        context = build_application_context(config_path, require_secrets=True)
        checks.append(_ok("config", "production config and required secrets are present"))
    except ConfigError as exc:
        checks.append(_fail("config", str(exc)))
    except Exception as exc:
        checks.append(_fail("config", f"application context failed: {type(exc).__name__}: {exc}"))

    if context is not None:
        checks.extend(_storage_checks(context))
        checks.append(_ok("llm", "OpenAI gateway is configured" if context.llm_gateway else "OpenAI gateway disabled"))
        context.close()

    checks.append(_discord_package_check(require_discord_package=require_discord_package))
    checks.append(_ffmpeg_check())
    return PreflightReport(checks=tuple(checks))


def _storage_checks(context: ApplicationContext) -> tuple[PreflightCheck, ...]:
    checks: list[PreflightCheck] = []
    try:
        context.connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        checks.append(_ok("database", "schema is migrated and queryable"))
    except Exception as exc:
        checks.append(_fail("database", f"schema query failed: {type(exc).__name__}"))

    for name, root in (
        ("raw_gpx_path", context.runtime.config.storage.raw_gpx_path),
        ("artifact_path", context.runtime.config.storage.artifact_path),
    ):
        checks.append(_write_probe(name, root))
    if context.runtime.config.public_artifacts.path is not None:
        checks.append(_write_probe("public_artifacts_path", context.runtime.config.public_artifacts.path))
    return tuple(checks)


def _write_probe(name: str, root: Path) -> PreflightCheck:
    probe = Path(".aimo-preflight-write-test")
    try:
        written = write_bytes_under(root, probe, b"ok")
        written.unlink(missing_ok=True)
        return _ok(name, f"{root} is writable")
    except Exception as exc:
        return _fail(name, f"{root} is not writable: {type(exc).__name__}")


def _discord_package_check(*, require_discord_package: bool) -> PreflightCheck:
    if importlib.util.find_spec("discord") is not None:
        return _ok("discord.py", "discord package is importable")
    if require_discord_package:
        return _fail("discord.py", "discord package is not installed")
    return _ok("discord.py", "discord package check skipped")


def _ffmpeg_check() -> PreflightCheck:
    if _ffmpeg_executable() is not None:
        return _ok("ffmpeg", "ffmpeg is available for WebM overlay encoding")
    return _fail("ffmpeg", "ffmpeg or the imageio-ffmpeg package is required for WebM overlay encoding")


def _ok(name: str, message: str) -> PreflightCheck:
    return PreflightCheck(name=name, ok=True, message=message)


def _fail(name: str, message: str) -> PreflightCheck:
    return PreflightCheck(name=name, ok=False, message=message)
