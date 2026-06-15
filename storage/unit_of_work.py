from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from types import TracebackType

from storage.repositories import (
    ActiveWorkoutRepository,
    AttachmentsRepository,
    ChannelsRepository,
    DebugTraceRepository,
    HeartRateZonesRepository,
    HistoryRepository,
    RenderedArtifactsRepository,
    UsersRepository,
    WorkoutStreamsRepository,
    WorkoutsRepository,
)
from storage.migrations import migrate
from storage.sqlite import load_schema, open_connection


@dataclass(frozen=True)
class RepositoryBundle:
    users: UsersRepository
    heart_rate_zones: HeartRateZonesRepository
    channels: ChannelsRepository
    history: HistoryRepository
    attachments: AttachmentsRepository
    workouts: WorkoutsRepository
    active_workouts: ActiveWorkoutRepository
    workout_streams: WorkoutStreamsRepository
    debug_traces: DebugTraceRepository
    rendered_artifacts: RenderedArtifactsRepository


def build_repositories(connection: sqlite3.Connection) -> RepositoryBundle:
    return RepositoryBundle(
        users=UsersRepository(connection),
        heart_rate_zones=HeartRateZonesRepository(connection),
        channels=ChannelsRepository(connection),
        history=HistoryRepository(connection),
        attachments=AttachmentsRepository(connection),
        workouts=WorkoutsRepository(connection),
        active_workouts=ActiveWorkoutRepository(connection),
        workout_streams=WorkoutStreamsRepository(connection),
        debug_traces=DebugTraceRepository(connection),
        rendered_artifacts=RenderedArtifactsRepository(connection),
    )


class UnitOfWork:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.repositories = build_repositories(connection)

    def __enter__(self) -> RepositoryBundle:
        return self.repositories

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        return False


def open_database(
    path: str = ":memory:",
    *,
    apply_schema: bool = False,
    apply_migrations: bool = False,
) -> sqlite3.Connection:
    connection = open_connection(path)
    if apply_migrations:
        migrate(connection)
        return connection
    if apply_schema:
        load_schema(connection)
    return connection
