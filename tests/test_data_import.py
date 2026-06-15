from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from aimo import main
from storage.importer import IMPORT_FORMAT, ImportValidationError, import_payload
from storage.unit_of_work import UnitOfWork, open_database


class DataImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)

    def tearDown(self) -> None:
        self.connection.close()

    def test_dry_run_validates_and_reports_without_writing(self) -> None:
        payload = _payload()

        report = import_payload(self.connection, payload, dry_run=True)

        self.assertTrue(report.dry_run)
        self.assertEqual(report.counts["users"], 2)
        with UnitOfWork(self.connection) as repositories:
            self.assertIsNone(repositories.users.get("user-1"))
            self.assertEqual(repositories.workouts.list_for_user("user-1"), ())

    def test_apply_imports_key_records_and_leaves_raw_gpx_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_file = Path(tmpdir) / "run.gpx"
            raw_bytes = b"<gpx><trk /></gpx>"
            raw_file.write_bytes(raw_bytes)
            payload = _payload(source_path=str(raw_file))

            report = import_payload(self.connection, payload, dry_run=False)

            self.assertFalse(report.dry_run)
            self.assertEqual(report.counts["attachments"], 1)
            self.assertEqual(raw_file.read_bytes(), raw_bytes)
            with UnitOfWork(self.connection) as repositories:
                user = repositories.users.get("user-1")
                zones = repositories.heart_rate_zones.list_for_user("user-1")
                history = repositories.history.list_recent_for_channel("channel-1")
                attachment = repositories.attachments.get("attachment-1")
                workouts = repositories.workouts.list_for_user("user-1")
                active = repositories.active_workouts.get("user-1")

            self.assertEqual(user.discord_display_name, "Runner One")
            self.assertEqual([zone.zone_key for zone in zones], ["z1", "z2"])
            self.assertEqual([record.history_id for record in history], ["history-1", "history-2"])
            self.assertEqual(attachment.raw_path, "legacy/raw/run.gpx")
            self.assertEqual(workouts[0].workout_id, "workout-1")
            self.assertEqual(active.workout_id, "workout-1")
            summary = self.connection.execute(
                "SELECT summary, turn_count FROM channel_summaries WHERE channel_id = ?",
                ("channel-1",),
            ).fetchone()
            tags = self.connection.execute(
                "SELECT tag FROM workout_tags WHERE workout_id = ? ORDER BY tag",
                ("workout-1",),
            ).fetchall()
            self.assertEqual(summary["summary"], "User discussed the imported run.")
            self.assertEqual(summary["turn_count"], 2)
            self.assertEqual([row["tag"] for row in tags], ["easy", "run"])

    def test_import_rejects_active_workout_owned_by_another_user(self) -> None:
        payload = _payload()
        payload["active_workouts"][0]["user_id"] = "user-2"

        with self.assertRaises(ImportValidationError):
            import_payload(self.connection, payload, dry_run=True)

        with UnitOfWork(self.connection) as repositories:
            self.assertIsNone(repositories.users.get("user-1"))

    def test_import_rejects_existing_primary_keys_before_writing(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-01T09:00:00Z")

        with self.assertRaises(ImportValidationError):
            import_payload(self.connection, _payload(), dry_run=True)

        with UnitOfWork(self.connection) as repositories:
            self.assertIsNone(repositories.users.get("user-2"))

    def test_import_rejects_duplicate_active_workout_rows_in_payload(self) -> None:
        payload = _payload()
        payload["active_workouts"].append(dict(payload["active_workouts"][0]))

        with self.assertRaises(ImportValidationError):
            import_payload(self.connection, payload, dry_run=True)

    def test_cli_import_dry_run_uses_configured_database_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = root / "aimo.conf"
            database = root / "aimo.sqlite3"
            import_file = root / "import.json"
            config.write_text("[storage]\n" f"database_path = {database}\n", encoding="utf-8")
            import_file.write_text(json.dumps(_payload()), encoding="utf-8")

            stdout = StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["--config", str(config), "--import-data", str(import_file), "--dry-run"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Aimo import dry-run OK", stdout.getvalue())
            connection = open_database(database, apply_migrations=True)
            try:
                with UnitOfWork(connection) as repositories:
                    self.assertIsNone(repositories.users.get("user-1"))
            finally:
                connection.close()


def _payload(*, source_path: str = "") -> dict[str, object]:
    attachment = {
        "attachment_id": "attachment-1",
        "owner_user_id": "user-1",
        "guild_id": "guild-1",
        "channel_id": "channel-1",
        "message_id": "message-1",
        "filename": "run.gpx",
        "content_type": "application/gpx+xml",
        "size_bytes": 18,
        "sha256": "abc123",
        "raw_path": "legacy/raw/run.gpx",
        "created_at": "2026-06-01T10:00:00Z",
        "metadata": {"imported": True},
    }
    if source_path:
        attachment["source_path"] = source_path
    return {
        "format": IMPORT_FORMAT,
        "users": [
            {
                "user_id": "user-1",
                "discord_user_name": "runner",
                "discord_display_name": "Runner One",
                "first_seen_at": "2026-06-01T09:00:00Z",
                "last_seen_at": "2026-06-02T09:00:00Z",
                "last_seen_source": "import",
                "metadata": {"timezone": "Europe/Helsinki"},
            },
            {
                "user_id": "user-2",
                "first_seen_at": "2026-06-01T09:00:00Z",
            },
        ],
        "channels": [
            {
                "channel_id": "channel-1",
                "guild_id": "guild-1",
                "channel_name": "training",
            },
        ],
        "channel_summaries": [
            {
                "channel_id": "channel-1",
                "summary": "User discussed the imported run.",
                "updated_at": "2026-06-02T10:00:00Z",
                "turn_count": 2,
            },
        ],
        "heart_rate_zones": [
            {
                "user_id": "user-1",
                "zone_key": "z1",
                "label": "Easy",
                "upper_bpm": 130,
                "sort_order": 1,
            },
            {
                "user_id": "user-1",
                "zone_key": "z2",
                "label": "Steady",
                "lower_bpm": 131,
                "upper_bpm": 150,
                "sort_order": 2,
            },
        ],
        "history_events": [
            {
                "history_id": "history-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "user_id": "user-1",
                "role": "user",
                "event_type": "message",
                "content": "Imported hello",
                "source_event_id": "message-1",
                "created_at": "2026-06-01T10:00:00Z",
            },
            {
                "history_id": "history-2",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "role": "assistant",
                "event_type": "chat_reply",
                "content": "Imported reply",
                "source_event_id": "message-1",
                "created_at": "2026-06-01T10:00:01Z",
            },
        ],
        "attachments": [attachment],
        "workouts": [
            {
                "workout_id": "workout-1",
                "owner_user_id": "user-1",
                "source_attachment_id": "attachment-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "title": "Imported run",
                "kind": "run",
                "primary_kind": "run",
                "start_time_utc": "2026-06-01T10:00:00Z",
                "start_time_local": "2026-06-01T13:00:00+03:00",
                "local_date": "2026-06-01",
                "distance_km": 5.1,
                "duration_s": 1800,
                "pace_s_per_km": 352.9,
                "ascent_m": 42,
                "avg_hr_bpm": 140,
                "max_hr_bpm": 160,
                "point_count": 0,
                "created_at": "2026-06-01T10:01:00Z",
                "tags": ["run", "easy"],
                "metadata": {"source": "legacy-export"},
            },
        ],
        "active_workouts": [
            {
                "user_id": "user-1",
                "workout_id": "workout-1",
                "updated_at": "2026-06-01T10:02:00Z",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
