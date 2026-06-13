from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from core.config import AppConfig, load_app_config
from core.i18n import Translator, validate_catalogs


@dataclass(frozen=True)
class RuntimeContext:
    config: AppConfig
    translator: Translator
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def build_runtime(
    config_path: str | Path = "aimo.conf",
    *,
    require_secrets: bool = False,
) -> RuntimeContext:
    validate_catalogs()
    config = load_app_config(config_path, require_secrets=require_secrets)
    return RuntimeContext(
        config=config,
        translator=Translator(config.bot.language),
    )

