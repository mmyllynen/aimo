from __future__ import annotations

import sqlite3
import unittest

from storage.repositories import DebugTraceEventRecord
from storage.unit_of_work import UnitOfWork, open_database


class UnitOfWorkTests(unittest.TestCase):
    def test_unit_of_work_commits_successful_repository_operations(self) -> None:
        connection = open_database(apply_schema=True)
        try:
            with UnitOfWork(connection) as repositories:
                repositories.users.touch(user_id="user-1", seen_at="2026-06-13T10:00:00Z")
                repositories.channels.upsert(channel_id="channel-1", guild_id="guild-1")

            self.assertIsNotNone(UnitOfWork(connection).repositories.users.get("user-1"))
            self.assertIsNotNone(UnitOfWork(connection).repositories.channels.get("channel-1"))
        finally:
            connection.close()

    def test_unit_of_work_rolls_back_on_error(self) -> None:
        connection = open_database(apply_schema=True)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                with UnitOfWork(connection) as repositories:
                    repositories.users.touch(user_id="user-1", seen_at="2026-06-13T10:00:00Z")
                    repositories.debug_traces.add_event(
                        DebugTraceEventRecord(
                            trace_event_id="event-1",
                            trace_id="missing-trace",
                            stage="route",
                            level="error",
                            message="rollback",
                        )
                    )

            self.assertIsNone(UnitOfWork(connection).repositories.users.get("user-1"))
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()

