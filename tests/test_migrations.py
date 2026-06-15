from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storage.migrations import load_migrations, migrate, open_migrated_database
from storage.sqlite import StorageError, open_connection


class MigrationTests(unittest.TestCase):
    def test_default_schema_migration_applies_schema_once(self) -> None:
        connection = open_connection()
        try:
            first = migrate(connection)
            second = migrate(connection)
            users = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
            ).fetchone()
            versions = connection.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
        finally:
            connection.close()

        self.assertEqual(first.applied_versions, (1,))
        self.assertEqual(second.applied_versions, ())
        self.assertIsNotNone(users)
        self.assertEqual([row["version"] for row in versions], [1])

    def test_directory_migrations_run_in_version_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "0002_second.sql").write_text("INSERT INTO example (value) VALUES ('second');", encoding="utf-8")
            (root / "0001_initial.sql").write_text(
                "CREATE TABLE example (value TEXT NOT NULL);"
                "INSERT INTO example (value) VALUES ('first');",
                encoding="utf-8",
            )
            connection = open_connection()
            try:
                result = migrate(connection, migrations_path=root)
                values = connection.execute("SELECT value FROM example").fetchall()
            finally:
                connection.close()

        self.assertEqual(result.applied_versions, (1, 2))
        self.assertEqual([row["value"] for row in values], ["first", "second"])

    def test_duplicate_migration_versions_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "0001_initial.sql").write_text("SELECT 1;", encoding="utf-8")
            (root / "0001_duplicate.sql").write_text("SELECT 1;", encoding="utf-8")

            with self.assertRaises(StorageError):
                load_migrations(root)

    def test_open_migrated_database_returns_ready_connection(self) -> None:
        connection = open_migrated_database()
        try:
            row = connection.execute("SELECT COUNT(*) AS count FROM schema_version").fetchone()
        finally:
            connection.close()

        self.assertEqual(row["count"], 1)


if __name__ == "__main__":
    unittest.main()
