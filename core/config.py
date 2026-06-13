from __future__ import annotations

from configparser import ConfigParser, Error as ConfigParserError
from dataclasses import dataclass, field
from pathlib import Path

from core.i18n import DEFAULT_LANGUAGE, SupportedLanguage, parse_language


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BotConfig:
    language: SupportedLanguage = DEFAULT_LANGUAGE
    enabled: bool = True


@dataclass(frozen=True)
class DiscordConfig:
    token: str = ""


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = ""
    model: str = "gpt-5.5"
    max_tokens: int = 500


@dataclass(frozen=True)
class StorageConfig:
    database_path: Path = Path("data/aimo.sqlite3")
    artifact_path: Path = Path("artifacts")
    raw_gpx_path: Path = Path("data/raw_gpx")


@dataclass(frozen=True)
class AdminConfig:
    user_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class LimitsConfig:
    max_attachment_size_bytes: int = 25 * 1024 * 1024


@dataclass(frozen=True)
class HistoryConfig:
    retention_days: int = 365


@dataclass(frozen=True)
class DebugConfig:
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    bot: BotConfig = field(default_factory=BotConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)


def load_app_config(path: str | Path = "aimo.conf", *, require_secrets: bool = False) -> AppConfig:
    parser = ConfigParser()
    try:
        parser.read(path)
    except ConfigParserError as exc:
        raise ConfigError(f"Could not read config {path!s}: {exc}") from exc

    config = AppConfig(
        bot=BotConfig(
            language=parse_language(_get(parser, "bot", "language", fallback=None)),
            enabled=_getbool(parser, "bot", "enabled", fallback=True),
        ),
        discord=DiscordConfig(
            token=_get(parser, "discord", "token", fallback=""),
        ),
        openai=OpenAIConfig(
            api_key=_get(parser, "openai", "api_key", fallback=""),
            model=_get(parser, "openai", "model", fallback="gpt-5.5"),
            max_tokens=_getint(parser, "openai", "max_tokens", fallback=500),
        ),
        storage=StorageConfig(
            database_path=Path(_get(parser, "storage", "database_path", fallback="data/aimo.sqlite3")),
            artifact_path=Path(_get(parser, "storage", "artifact_path", fallback="artifacts")),
            raw_gpx_path=Path(_get(parser, "storage", "raw_gpx_path", fallback="data/raw_gpx")),
        ),
        admin=AdminConfig(
            user_ids=frozenset(_split_csv(_get(parser, "admin", "user_ids", fallback=""))),
        ),
        limits=LimitsConfig(
            max_attachment_size_bytes=_getint(
                parser,
                "limits",
                "max_attachment_size_bytes",
                fallback=25 * 1024 * 1024,
            ),
        ),
        history=HistoryConfig(
            retention_days=_getint(parser, "history", "retention_days", fallback=365),
        ),
        debug=DebugConfig(
            enabled=_getbool(parser, "debug", "enabled", fallback=True),
        ),
    )
    validate_config(config, require_secrets=require_secrets)
    return config


def validate_config(config: AppConfig, *, require_secrets: bool = False) -> None:
    if config.openai.max_tokens <= 0:
        raise ConfigError("openai.max_tokens must be positive")
    if config.limits.max_attachment_size_bytes <= 0:
        raise ConfigError("limits.max_attachment_size_bytes must be positive")
    if config.history.retention_days <= 0:
        raise ConfigError("history.retention_days must be positive")
    if not str(config.storage.database_path):
        raise ConfigError("storage.database_path must not be empty")
    if not str(config.storage.artifact_path):
        raise ConfigError("storage.artifact_path must not be empty")
    if not str(config.storage.raw_gpx_path):
        raise ConfigError("storage.raw_gpx_path must not be empty")
    if require_secrets:
        if not config.discord.token:
            raise ConfigError("discord.token is required in production mode")
        if not config.openai.api_key:
            raise ConfigError("openai.api_key is required in production mode")


def _get(parser: ConfigParser, section: str, option: str, *, fallback: str | None) -> str | None:
    return parser.get(section, option, fallback=fallback)


def _getint(parser: ConfigParser, section: str, option: str, *, fallback: int) -> int:
    try:
        return parser.getint(section, option, fallback=fallback)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be an integer") from exc


def _getbool(parser: ConfigParser, section: str, option: str, *, fallback: bool) -> bool:
    try:
        return parser.getboolean(section, option, fallback=fallback)
    except ValueError as exc:
        raise ConfigError(f"{section}.{option} must be a boolean") from exc


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())

