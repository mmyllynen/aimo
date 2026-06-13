from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class StorageError(RuntimeError):
    pass


def open_connection(path: str | Path = ":memory:") -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_schema(connection: sqlite3.Connection, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> None:
    path = Path(schema_path)
    try:
        schema = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageError(f"Could not read SQLite schema from {path}") from exc

    with transaction(connection):
        connection.executescript(schema)


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()

