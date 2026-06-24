from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from adapters.discord.attachments import hydrate_attachment_content
from app.dispatcher import DispatchContext, Dispatcher
from app.policy import AdminPolicy
from core.events import CanonicalEvent
from core.runtime import RuntimeContext, build_runtime
from llm.factory import build_openai_gateway
from llm.gateway import LLMGateway
from storage.unit_of_work import UnitOfWork, open_database
from weather.service import OpenMeteoWeatherProvider


@dataclass(frozen=True)
class ApplicationContext:
    runtime: RuntimeContext
    connection: sqlite3.Connection
    dispatcher: Dispatcher
    admin_policy: AdminPolicy
    llm_gateway: LLMGateway | None = None

    def dispatch_context(self) -> DispatchContext:
        return DispatchContext(
            unit_of_work=UnitOfWork(self.connection),
            admin_policy=self.admin_policy,
            language=self.runtime.config.bot.language,
            llm_gateway=self.llm_gateway,
            max_attachment_size_bytes=self.runtime.config.limits.max_attachment_size_bytes,
            raw_gpx_path=self.runtime.config.storage.raw_gpx_path,
            artifact_path=self.runtime.config.storage.artifact_path,
            public_artifacts=self.runtime.config.public_artifacts,
            maps_config=self.runtime.config.maps,
            weather_provider=_weather_provider(self.runtime.config.weather),
        )

    def dispatch_event(self, event: CanonicalEvent):
        return self.dispatcher.dispatch(event, self.dispatch_context())

    def dispatch_event_isolated(self, event: CanonicalEvent, *, status_callback: Callable[[str], None] | None = None):
        connection = open_database(str(self.runtime.config.storage.database_path))
        try:
            return self.dispatcher.dispatch(
                event,
                DispatchContext(
                    unit_of_work=UnitOfWork(connection),
                    admin_policy=self.admin_policy,
                    language=self.runtime.config.bot.language,
                    llm_gateway=self.llm_gateway,
                    max_attachment_size_bytes=self.runtime.config.limits.max_attachment_size_bytes,
                    raw_gpx_path=self.runtime.config.storage.raw_gpx_path,
                    artifact_path=self.runtime.config.storage.artifact_path,
                    public_artifacts=self.runtime.config.public_artifacts,
                    maps_config=self.runtime.config.maps,
                    weather_provider=_weather_provider(self.runtime.config.weather),
                    status_callback=status_callback,
                ),
            )
        finally:
            connection.close()

    def hydrate_attachments(self, event: CanonicalEvent) -> CanonicalEvent:
        return hydrate_attachment_content(
            event,
            max_size_bytes=self.runtime.config.limits.max_attachment_size_bytes,
        )

    def close(self) -> None:
        self.connection.close()


def build_application_context(
    config_path: str | Path = "aimo.conf",
    *,
    require_secrets: bool = False,
    apply_schema: bool = True,
    enable_llm: bool = True,
) -> ApplicationContext:
    runtime = build_runtime(config_path, require_secrets=require_secrets)
    database_path = runtime.config.storage.database_path
    _ensure_parent_dir(database_path)
    runtime.config.storage.raw_gpx_path.mkdir(parents=True, exist_ok=True)
    runtime.config.storage.artifact_path.mkdir(parents=True, exist_ok=True)
    if runtime.config.public_artifacts.path is not None:
        runtime.config.public_artifacts.path.mkdir(parents=True, exist_ok=True)
    connection = open_database(str(database_path), apply_migrations=apply_schema)
    llm_gateway = build_openai_gateway(runtime.config.openai) if enable_llm and runtime.config.openai.api_key else None
    return ApplicationContext(
        runtime=runtime,
        connection=connection,
        dispatcher=Dispatcher(),
        admin_policy=AdminPolicy(runtime.config.admin.user_ids),
        llm_gateway=llm_gateway,
    )


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if str(parent) and str(parent) != ".":
        parent.mkdir(parents=True, exist_ok=True)


def _weather_provider(config):
    if not config.enabled or config.provider == "none":
        return None
    return OpenMeteoWeatherProvider(timeout_s=config.timeout_s)
