from __future__ import annotations

import sqlite3
import unittest

from storage.sqlite import load_schema, open_connection, transaction


EXPECTED_TABLES = {
    "schema_version",
    "users",
    "heart_rate_zones",
    "guild_policies",
    "channels",
    "channel_summaries",
    "history_events",
    "attachments",
    "workouts",
    "active_workouts",
    "workout_tags",
    "workout_points",
    "workout_streams",
    "workout_estimate_features",
    "debug_traces",
    "debug_trace_events",
    "rendered_artifacts",
}


class StorageTests(unittest.TestCase):
    def test_open_connection_enables_foreign_keys_and_row_factory(self) -> None:
        connection = open_connection()
        try:
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            row = connection.execute("SELECT 1 AS value").fetchone()
        finally:
            connection.close()

        self.assertEqual(foreign_keys, 1)
        self.assertEqual(row["value"], 1)

    def test_load_schema_creates_expected_tables(self) -> None:
        connection = open_connection()
        try:
            load_schema(connection)
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        finally:
            connection.close()

        table_names = {row["name"] for row in rows}
        self.assertTrue(EXPECTED_TABLES.issubset(table_names))

    def test_schema_supports_core_insert_flow(self) -> None:
        connection = open_connection()
        try:
            load_schema(connection)
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id,
                        discord_user_name,
                        discord_display_name,
                        first_seen_at,
                        last_seen_at,
                        last_seen_source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    ("user-1", "runner", "Runner", "2026-06-13T00:00:00Z", "2026-06-13T00:00:00Z", "test"),
                )
                connection.execute(
                    """
                    INSERT INTO channels (
                        channel_id,
                        guild_id,
                        channel_name
                    ) VALUES (?, ?, ?)
                    """,
                    ("channel-1", "guild-1", "training"),
                )
                connection.execute(
                    """
                    INSERT INTO history_events (
                        history_id,
                        guild_id,
                        channel_id,
                        user_id,
                        role,
                        event_type,
                        content,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "history-1",
                        "guild-1",
                        "channel-1",
                        "user-1",
                        "user",
                        "mention",
                        "@Aimo hello",
                        "2026-06-13T00:00:00Z",
                    ),
                )

            history = connection.execute(
                "SELECT content FROM history_events WHERE history_id = ?",
                ("history-1",),
            ).fetchone()
        finally:
            connection.close()

        self.assertEqual(history["content"], "@Aimo hello")

    def test_transaction_rolls_back_on_error(self) -> None:
        connection = open_connection()
        try:
            load_schema(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                with transaction(connection):
                    connection.execute(
                        """
                        INSERT INTO users (
                            user_id,
                            first_seen_at,
                            last_seen_at
                        ) VALUES (?, ?, ?)
                        """,
                        ("user-1", "2026-06-13T00:00:00Z", "2026-06-13T00:00:00Z"),
                    )
                    connection.execute(
                        """
                        INSERT INTO heart_rate_zones (
                            user_id,
                            zone_key,
                            label
                        ) VALUES (?, ?, ?)
                        """,
                        ("missing-user", "z1", "Zone 1"),
                    )

            count = connection.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        finally:
            connection.close()

        self.assertEqual(count["count"], 0)


if __name__ == "__main__":
    unittest.main()
