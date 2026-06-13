from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from storage.sqlite import DEFAULT_SCHEMA_PATH, StorageError, open_connection, transaction


MIGRATION_NAME_RE = re.compile(r"^(?P<version>\d+)[_-].+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path


@dataclass(frozen=True)
class MigrationResult:
    applied_versions: tuple[int, ...]


def load_migrations(path: str | Path = DEFAULT_SCHEMA_PATH) -> tuple[Migration, ...]:
    migration_path = Path(path)
    if migration_path.is_file():
        return (Migration(version=1, name=migration_path.name, path=migration_path),)
    if not migration_path.is_dir():
        raise StorageError(f"Migration path does not exist: {migration_path}")

    migrations = []
    for sql_file in sorted(migration_path.glob("*.sql")):
        match = MIGRATION_NAME_RE.match(sql_file.name)
        if match is None:
            continue
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=sql_file.name,
                path=sql_file,
            )
        )
    _validate_migrations(tuple(migrations), migration_path)
    return tuple(migrations)


def migrate(connection: sqlite3.Connection, migrations_path: str | Path = DEFAULT_SCHEMA_PATH) -> MigrationResult:
    migrations = load_migrations(migrations_path)
    _ensure_schema_version_table(connection)
    applied = _applied_versions(connection)
    newly_applied: list[int] = []
    for migration in migrations:
        if migration.version in applied:
            continue
        script = _read_migration(migration)
        with transaction(connection):
            connection.executescript(script)
            connection.execute(
                """
                INSERT INTO schema_version (version, applied_at)
                VALUES (?, ?)
                """,
                (migration.version, _now()),
            )
        newly_applied.append(migration.version)
    return MigrationResult(applied_versions=tuple(newly_applied))


def open_migrated_database(
    path: str | Path = ":memory:",
    *,
    migrations_path: str | Path = DEFAULT_SCHEMA_PATH,
) -> sqlite3.Connection:
    connection = open_connection(path)
    migrate(connection, migrations_path=migrations_path)
    return connection


def _ensure_schema_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def _applied_versions(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute("SELECT version FROM schema_version").fetchall()
    return {int(row["version"]) for row in rows}


def _read_migration(migration: Migration) -> str:
    try:
        return migration.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not read migration {migration.path}") from exc


def _validate_migrations(migrations: tuple[Migration, ...], path: Path) -> None:
    if not migrations:
        raise StorageError(f"No numbered SQL migrations found in {path}")
    seen: set[int] = set()
    duplicates = []
    for migration in migrations:
        if migration.version in seen:
            duplicates.append(migration.version)
        seen.add(migration.version)
    if duplicates:
        duplicate_text = ", ".join(str(version) for version in sorted(set(duplicates)))
        raise StorageError(f"Duplicate migration versions: {duplicate_text}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
