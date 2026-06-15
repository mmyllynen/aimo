from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from storage.repositories import (
    AttachmentRecord,
    HistoryEventRecord,
    WorkoutRecord,
)
from storage.sqlite import StorageError
from storage.unit_of_work import build_repositories


IMPORT_FORMAT = "aimo.v3.import.v1"


class ImportValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ImportReport:
    dry_run: bool
    format: str
    counts: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def total_imported(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        mode = "dry-run" if self.dry_run else "apply"
        count_text = ", ".join(f"{key}={value}" for key, value in sorted(self.counts.items()))
        return f"Aimo import {mode} OK: {count_text or 'no records'}"


def import_json_file(connection: sqlite3.Connection, path: str | Path, *, dry_run: bool = False) -> ImportReport:
    payload = _read_payload(path)
    return import_payload(connection, payload, dry_run=dry_run)


def import_payload(connection: sqlite3.Connection, payload: dict[str, Any], *, dry_run: bool = False) -> ImportReport:
    _validate_payload_shape(payload)
    _validate_no_existing_records(connection, payload)
    counts = _counts(payload)
    warnings = _warnings(payload)

    connection.execute("SAVEPOINT aimo_import")
    try:
        _apply_payload(connection, payload)
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT aimo_import")
        connection.execute("RELEASE SAVEPOINT aimo_import")
        raise
    if dry_run:
        connection.execute("ROLLBACK TO SAVEPOINT aimo_import")
    connection.execute("RELEASE SAVEPOINT aimo_import")

    return ImportReport(
        dry_run=dry_run,
        format=IMPORT_FORMAT,
        counts=counts,
        warnings=tuple(warnings),
    )


def _read_payload(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        raw = source.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except OSError as exc:
        raise StorageError(f"Could not read import file: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ImportValidationError(f"Import file is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ImportValidationError("Import payload must be a JSON object")
    return payload


def _validate_payload_shape(payload: dict[str, Any]) -> None:
    if payload.get("format") != IMPORT_FORMAT:
        raise ImportValidationError(f"Unsupported import format: {payload.get('format')!r}")
    for key in _collection_keys():
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise ImportValidationError(f"{key} must be a list")

    user_ids = _ids(payload.get("users", []), "user_id", "users")
    channel_ids = _ids(payload.get("channels", []), "channel_id", "channels")
    _ids(payload.get("channel_summaries", []), "channel_id", "channel_summaries")
    _ids(payload.get("history_events", []), "history_id", "history_events")
    _ids(payload.get("attachments", []), "attachment_id", "attachments")
    _ids(payload.get("workouts", []), "workout_id", "workouts")
    _ids(payload.get("active_workouts", []), "user_id", "active_workouts")
    _validate_unique_hr_zones(payload.get("heart_rate_zones", []))
    attachment_owners: dict[str, str] = {}
    workout_owners: dict[str, str] = {}

    for user in payload.get("users", []):
        _require(user, "users", "user_id")
        if not user.get("first_seen_at") and not user.get("last_seen_at"):
            raise ImportValidationError("users.first_seen_at or users.last_seen_at is required")

    for zone in payload.get("heart_rate_zones", []):
        _require(zone, "heart_rate_zones", "user_id", "zone_key", "label")
        _require_known(zone["user_id"], user_ids, "heart_rate_zones.user_id")

    for summary in payload.get("channel_summaries", []):
        _require(summary, "channel_summaries", "channel_id", "summary", "updated_at")
        _require_known(summary["channel_id"], channel_ids, "channel_summaries.channel_id")

    for history in payload.get("history_events", []):
        _require(history, "history_events", "history_id", "channel_id", "role", "event_type", "created_at")
        _require_known(history["channel_id"], channel_ids, "history_events.channel_id")
        user_id = history.get("user_id")
        if user_id is not None:
            _require_known(user_id, user_ids, "history_events.user_id")

    for attachment in payload.get("attachments", []):
        _require(
            attachment,
            "attachments",
            "attachment_id",
            "owner_user_id",
            "filename",
            "sha256",
            "raw_path",
            "created_at",
        )
        _require_known(attachment["owner_user_id"], user_ids, "attachments.owner_user_id")
        channel_id = attachment.get("channel_id")
        if channel_id is not None:
            _require_known(channel_id, channel_ids, "attachments.channel_id")
        attachment_owners[attachment["attachment_id"]] = attachment["owner_user_id"]

    for workout in payload.get("workouts", []):
        _require(workout, "workouts", "workout_id", "owner_user_id", "title", "kind", "created_at")
        _require_known(workout["owner_user_id"], user_ids, "workouts.owner_user_id")
        source_attachment_id = workout.get("source_attachment_id")
        if source_attachment_id is not None:
            _require_known(source_attachment_id, set(attachment_owners), "workouts.source_attachment_id")
            if attachment_owners[source_attachment_id] != workout["owner_user_id"]:
                raise ImportValidationError("workouts.source_attachment_id must belong to the workout owner")
        channel_id = workout.get("channel_id")
        if channel_id is not None:
            _require_known(channel_id, channel_ids, "workouts.channel_id")
        workout_owners[workout["workout_id"]] = workout["owner_user_id"]

    for active in payload.get("active_workouts", []):
        _require(active, "active_workouts", "user_id", "workout_id", "updated_at")
        _require_known(active["user_id"], user_ids, "active_workouts.user_id")
        _require_known(active["workout_id"], set(workout_owners), "active_workouts.workout_id")
        if workout_owners[active["workout_id"]] != active["user_id"]:
            raise ImportValidationError("active_workouts.workout_id must belong to active_workouts.user_id")


def _apply_payload(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    repositories = build_repositories(connection)
    for user in payload.get("users", []):
        repositories.users.touch(
            user_id=user["user_id"],
            discord_user_name=str(user.get("discord_user_name", "")),
            discord_display_name=str(user.get("discord_display_name", "")),
            seen_at=str(user.get("first_seen_at") or user.get("last_seen_at")),
            source=str(user.get("last_seen_source", "import")),
            metadata=_metadata(user),
        )
        last_seen_at = user.get("last_seen_at")
        if last_seen_at:
            repositories.users.touch(
                user_id=user["user_id"],
                discord_user_name=str(user.get("discord_user_name", "")),
                discord_display_name=str(user.get("discord_display_name", "")),
                seen_at=str(last_seen_at),
                source=str(user.get("last_seen_source", "import")),
                metadata=_metadata(user),
            )

    for channel in payload.get("channels", []):
        repositories.channels.upsert(
            channel_id=channel["channel_id"],
            guild_id=channel.get("guild_id"),
            channel_name=str(channel.get("channel_name", "")),
            metadata=_metadata(channel),
        )

    for summary in payload.get("channel_summaries", []):
        connection.execute(
            """
            INSERT INTO channel_summaries (channel_id, summary, updated_at, turn_count)
            VALUES (?, ?, ?, ?)
            """,
            (
                summary["channel_id"],
                str(summary.get("summary", "")),
                summary["updated_at"],
                int(summary.get("turn_count", 0)),
            ),
        )

    for zone in payload.get("heart_rate_zones", []):
        connection.execute(
            """
            INSERT INTO heart_rate_zones (user_id, zone_key, label, lower_bpm, upper_bpm, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                zone["user_id"],
                zone["zone_key"],
                zone["label"],
                zone.get("lower_bpm"),
                zone.get("upper_bpm"),
                int(zone.get("sort_order", 0)),
            ),
        )

    for history in payload.get("history_events", []):
        repositories.history.add(
            HistoryEventRecord(
                history_id=history["history_id"],
                guild_id=history.get("guild_id"),
                channel_id=history["channel_id"],
                user_id=history.get("user_id"),
                role=history["role"],
                event_type=history["event_type"],
                content=str(history.get("content", "")),
                source_event_id=history.get("source_event_id"),
                created_at=history["created_at"],
                metadata=_metadata(history),
            )
        )

    for attachment in payload.get("attachments", []):
        repositories.attachments.add(
            AttachmentRecord(
                attachment_id=attachment["attachment_id"],
                owner_user_id=attachment["owner_user_id"],
                guild_id=attachment.get("guild_id"),
                channel_id=attachment.get("channel_id"),
                message_id=attachment.get("message_id"),
                filename=attachment["filename"],
                content_type=str(attachment.get("content_type", "")),
                size_bytes=attachment.get("size_bytes"),
                sha256=attachment["sha256"],
                raw_path=attachment["raw_path"],
                created_at=attachment["created_at"],
                metadata=_metadata(attachment),
            )
        )

    for workout in payload.get("workouts", []):
        repositories.workouts.add(
            WorkoutRecord(
                workout_id=workout["workout_id"],
                owner_user_id=workout["owner_user_id"],
                source_attachment_id=workout.get("source_attachment_id"),
                guild_id=workout.get("guild_id"),
                channel_id=workout.get("channel_id"),
                title=workout["title"],
                kind=workout["kind"],
                primary_kind=str(workout.get("primary_kind", workout.get("kind", ""))),
                start_time_utc=workout.get("start_time_utc"),
                start_time_local=workout.get("start_time_local"),
                local_date=workout.get("local_date"),
                distance_km=workout.get("distance_km"),
                duration_s=workout.get("duration_s"),
                pace_s_per_km=workout.get("pace_s_per_km"),
                ascent_m=workout.get("ascent_m"),
                avg_hr_bpm=workout.get("avg_hr_bpm"),
                max_hr_bpm=workout.get("max_hr_bpm"),
                point_count=int(workout.get("point_count", 0)),
                created_at=workout["created_at"],
                schema_version=int(workout.get("schema_version", 1)),
                metadata=_metadata(workout),
            )
        )
        for tag in workout.get("tags", []):
            connection.execute(
                "INSERT INTO workout_tags (workout_id, tag) VALUES (?, ?)",
                (workout["workout_id"], str(tag)),
            )

    for active in payload.get("active_workouts", []):
        repositories.active_workouts.set(
            user_id=active["user_id"],
            workout_id=active["workout_id"],
            updated_at=active["updated_at"],
        )


def _counts(payload: dict[str, Any]) -> dict[str, int]:
    return {key: len(payload.get(key, [])) for key in _collection_keys()}


def _warnings(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for attachment in payload.get("attachments", []):
        source_path = attachment.get("source_path")
        if source_path and not Path(str(source_path)).exists():
            warnings.append(f"Attachment source_path does not exist: {source_path}")
    return warnings


def _validate_no_existing_records(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    checks = (
        ("users", "user_id", "users", "user_id"),
        ("channels", "channel_id", "channels", "channel_id"),
        ("channel_summaries", "channel_id", "channel_summaries", "channel_id"),
        ("history_events", "history_id", "history_events", "history_id"),
        ("attachments", "attachment_id", "attachments", "attachment_id"),
        ("workouts", "workout_id", "workouts", "workout_id"),
        ("active_workouts", "user_id", "active_workouts", "user_id"),
    )
    for collection, payload_key, table, column in checks:
        for record in payload.get(collection, []):
            value = record[payload_key]
            if _exists(connection, table, column, value):
                raise ImportValidationError(f"{collection}.{payload_key} already exists: {value}")
    for zone in payload.get("heart_rate_zones", []):
        row = connection.execute(
            """
            SELECT 1
            FROM heart_rate_zones
            WHERE user_id = ? AND zone_key = ?
            LIMIT 1
            """,
            (zone["user_id"], zone["zone_key"]),
        ).fetchone()
        if row is not None:
            raise ImportValidationError(
                f"heart_rate_zones already exists: {zone['user_id']}:{zone['zone_key']}"
            )


def _exists(connection: sqlite3.Connection, table: str, column: str, value: str) -> bool:
    row = connection.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1",
        (value,),
    ).fetchone()
    return row is not None


def _collection_keys() -> tuple[str, ...]:
    return (
        "users",
        "channels",
        "channel_summaries",
        "heart_rate_zones",
        "history_events",
        "attachments",
        "workouts",
        "active_workouts",
    )


def _ids(records: list[Any], key: str, collection: str) -> set[str]:
    ids: set[str] = set()
    for record in records:
        _require(record, collection, key)
        value = record[key]
        if value in ids:
            raise ImportValidationError(f"Duplicate {collection}.{key}: {value}")
        ids.add(value)
    return ids


def _validate_unique_hr_zones(records: list[Any]) -> None:
    seen: set[tuple[str, str]] = set()
    for record in records:
        _require(record, "heart_rate_zones", "user_id", "zone_key")
        key = (record["user_id"], record["zone_key"])
        if key in seen:
            raise ImportValidationError(f"Duplicate heart_rate_zones key: {key[0]}:{key[1]}")
        seen.add(key)


def _require(record: Any, collection: str, *keys: str) -> None:
    if not isinstance(record, dict):
        raise ImportValidationError(f"{collection} entries must be objects")
    for key in keys:
        if key not in record or record[key] in {"", None}:
            raise ImportValidationError(f"{collection}.{key} is required")


def _require_known(value: str, known: set[str], field: str) -> None:
    if value not in known:
        raise ImportValidationError(f"{field} references unknown id: {value}")


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ImportValidationError("metadata must be an object when present")
    return metadata
