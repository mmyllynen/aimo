from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    discord_user_name: str
    discord_display_name: str
    first_seen_at: str
    last_seen_at: str
    last_seen_source: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelRecord:
    channel_id: str
    guild_id: str | None
    channel_name: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class HeartRateZoneRecord:
    user_id: str
    zone_key: str
    label: str
    lower_bpm: int | None = None
    upper_bpm: int | None = None
    sort_order: int = 0


@dataclass(frozen=True)
class HistoryEventRecord:
    history_id: str
    guild_id: str | None
    channel_id: str
    user_id: str | None
    role: str
    event_type: str
    content: str
    source_event_id: str | None
    created_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class DebugTraceRecord:
    trace_id: str
    source_event_id: str | None
    workflow: str
    status: str
    started_at: str
    finished_at: str | None
    payload: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class DebugTraceEventRecord:
    trace_event_id: str
    trace_id: str
    stage: str
    level: str
    message: str
    payload: JsonObject = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: str
    owner_user_id: str
    guild_id: str | None
    channel_id: str | None
    message_id: str | None
    filename: str
    content_type: str
    size_bytes: int | None
    sha256: str
    raw_path: str
    created_at: str
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class WorkoutRecord:
    workout_id: str
    owner_user_id: str
    source_attachment_id: str | None
    guild_id: str | None
    channel_id: str | None
    title: str
    kind: str
    primary_kind: str
    start_time_utc: str | None
    start_time_local: str | None
    local_date: str | None
    distance_km: float | None
    duration_s: float | None
    pace_s_per_km: float | None
    ascent_m: float | None
    avg_hr_bpm: float | None
    max_hr_bpm: float | None
    point_count: int
    created_at: str
    schema_version: int = 1
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class WorkoutPointRecord:
    workout_id: str
    point_index: int
    timestamp_utc: str | None = None
    elapsed_s: float | None = None
    distance_m: float | None = None
    distance_km: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    heart_rate_bpm: float | None = None
    cadence_spm: float | None = None
    pace_s_per_km: float | None = None
    segment_index: int | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class WorkoutStreamRecord:
    workout_id: str
    stream_key: str
    unit: str = ""
    sample_count: int = 0
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class RenderedArtifactRecord:
    artifact_id: str
    owner_user_id: str
    workflow_trace_id: str | None
    artifact_type: str
    filename: str
    content_type: str
    storage_path: str
    created_at: str
    metadata: JsonObject = field(default_factory=dict)


class UsersRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def touch(
        self,
        *,
        user_id: str,
        discord_user_name: str = "",
        discord_display_name: str = "",
        seen_at: datetime | str | None = None,
        source: str = "",
        metadata: JsonObject | None = None,
    ) -> UserRecord:
        timestamp = _timestamp(seen_at)
        self.connection.execute(
            """
            INSERT INTO users (
                user_id,
                discord_user_name,
                discord_display_name,
                first_seen_at,
                last_seen_at,
                last_seen_source,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                discord_user_name = excluded.discord_user_name,
                discord_display_name = excluded.discord_display_name,
                last_seen_at = excluded.last_seen_at,
                last_seen_source = excluded.last_seen_source,
                metadata_json = excluded.metadata_json
            """,
            (
                user_id,
                discord_user_name,
                discord_display_name,
                timestamp,
                timestamp,
                source,
                _to_json(metadata or {}),
            ),
        )
        record = self.get(user_id)
        if record is None:
            raise RuntimeError(f"User upsert failed for {user_id}")
        return record

    def get(self, user_id: str) -> UserRecord | None:
        row = self.connection.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return _user_from_row(row)


class ChannelsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def upsert(
        self,
        *,
        channel_id: str,
        guild_id: str | None = None,
        channel_name: str = "",
        metadata: JsonObject | None = None,
    ) -> ChannelRecord:
        self.connection.execute(
            """
            INSERT INTO channels (
                channel_id,
                guild_id,
                channel_name,
                metadata_json
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_name = excluded.channel_name,
                metadata_json = excluded.metadata_json
            """,
            (channel_id, guild_id, channel_name, _to_json(metadata or {})),
        )
        record = self.get(channel_id)
        if record is None:
            raise RuntimeError(f"Channel upsert failed for {channel_id}")
        return record

    def get(self, channel_id: str) -> ChannelRecord | None:
        row = self.connection.execute(
            "SELECT * FROM channels WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        if row is None:
            return None
        return _channel_from_row(row)


class HistoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, record: HistoryEventRecord) -> HistoryEventRecord:
        self.connection.execute(
            """
            INSERT INTO history_events (
                history_id,
                guild_id,
                channel_id,
                user_id,
                role,
                event_type,
                content,
                source_event_id,
                created_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.history_id,
                record.guild_id,
                record.channel_id,
                record.user_id,
                record.role,
                record.event_type,
                record.content,
                record.source_event_id,
                record.created_at,
                _to_json(record.metadata),
            ),
        )
        return record

    def list_recent_for_channel(self, channel_id: str, *, limit: int = 50) -> tuple[HistoryEventRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM history_events
            WHERE channel_id = ?
            ORDER BY created_at DESC, history_id DESC
            LIMIT ?
            """,
            (channel_id, limit),
        ).fetchall()
        return tuple(reversed([_history_from_row(row) for row in rows]))


class HeartRateZonesRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def replace_for_user(self, user_id: str, zones: tuple[HeartRateZoneRecord, ...]) -> None:
        self.connection.execute("DELETE FROM heart_rate_zones WHERE user_id = ?", (user_id,))
        for zone in zones:
            if zone.user_id != user_id:
                raise ValueError("Heart-rate zone user_id does not match replacement user_id")
            self.connection.execute(
                """
                INSERT INTO heart_rate_zones (
                    user_id,
                    zone_key,
                    label,
                    lower_bpm,
                    upper_bpm,
                    sort_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    zone.user_id,
                    zone.zone_key,
                    zone.label,
                    zone.lower_bpm,
                    zone.upper_bpm,
                    zone.sort_order,
                ),
            )

    def list_for_user(self, user_id: str) -> tuple[HeartRateZoneRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM heart_rate_zones
            WHERE user_id = ?
            ORDER BY sort_order ASC, zone_key ASC
            """,
            (user_id,),
        ).fetchall()
        return tuple(_heart_rate_zone_from_row(row) for row in rows)


class AttachmentsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, record: AttachmentRecord) -> AttachmentRecord:
        self.connection.execute(
            """
            INSERT INTO attachments (
                attachment_id,
                owner_user_id,
                guild_id,
                channel_id,
                message_id,
                filename,
                content_type,
                size_bytes,
                sha256,
                raw_path,
                created_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.attachment_id,
                record.owner_user_id,
                record.guild_id,
                record.channel_id,
                record.message_id,
                record.filename,
                record.content_type,
                record.size_bytes,
                record.sha256,
                record.raw_path,
                record.created_at,
                _to_json(record.metadata),
            ),
        )
        return record

    def get(self, attachment_id: str) -> AttachmentRecord | None:
        row = self.connection.execute(
            "SELECT * FROM attachments WHERE attachment_id = ?",
            (attachment_id,),
        ).fetchone()
        if row is None:
            return None
        return _attachment_from_row(row)

    def find_by_sha256(self, owner_user_id: str, sha256: str) -> AttachmentRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM attachments
            WHERE owner_user_id = ? AND sha256 = ?
            ORDER BY created_at DESC, attachment_id DESC
            LIMIT 1
            """,
            (owner_user_id, sha256),
        ).fetchone()
        if row is None:
            return None
        return _attachment_from_row(row)


class WorkoutsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, record: WorkoutRecord) -> WorkoutRecord:
        self.connection.execute(
            """
            INSERT INTO workouts (
                workout_id,
                owner_user_id,
                source_attachment_id,
                guild_id,
                channel_id,
                title,
                kind,
                primary_kind,
                start_time_utc,
                start_time_local,
                local_date,
                distance_km,
                duration_s,
                pace_s_per_km,
                ascent_m,
                avg_hr_bpm,
                max_hr_bpm,
                point_count,
                created_at,
                schema_version,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.workout_id,
                record.owner_user_id,
                record.source_attachment_id,
                record.guild_id,
                record.channel_id,
                record.title,
                record.kind,
                record.primary_kind,
                record.start_time_utc,
                record.start_time_local,
                record.local_date,
                record.distance_km,
                record.duration_s,
                record.pace_s_per_km,
                record.ascent_m,
                record.avg_hr_bpm,
                record.max_hr_bpm,
                record.point_count,
                record.created_at,
                record.schema_version,
                _to_json(record.metadata),
            ),
        )
        return record

    def get_for_user(self, owner_user_id: str, workout_id: str) -> WorkoutRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM workouts
            WHERE owner_user_id = ? AND workout_id = ?
            """,
            (owner_user_id, workout_id),
        ).fetchone()
        if row is None:
            return None
        return _workout_from_row(row)

    def list_for_user(self, owner_user_id: str, *, limit: int = 20) -> tuple[WorkoutRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM workouts
            WHERE owner_user_id = ?
            ORDER BY start_time_local DESC, created_at DESC, workout_id DESC
            LIMIT ?
            """,
            (owner_user_id, limit),
        ).fetchall()
        return tuple(_workout_from_row(row) for row in rows)

    def latest_for_user(self, owner_user_id: str) -> WorkoutRecord | None:
        rows = self.list_for_user(owner_user_id, limit=1)
        if not rows:
            return None
        return rows[0]

    def find_by_source_attachment(self, owner_user_id: str, source_attachment_id: str) -> WorkoutRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM workouts
            WHERE owner_user_id = ? AND source_attachment_id = ?
            ORDER BY created_at DESC, workout_id DESC
            LIMIT 1
            """,
            (owner_user_id, source_attachment_id),
        ).fetchone()
        if row is None:
            return None
        return _workout_from_row(row)

    def delete_for_user(self, owner_user_id: str, workout_id: str) -> bool:
        cursor = self.connection.execute(
            """
            DELETE FROM workouts
            WHERE owner_user_id = ? AND workout_id = ?
            """,
            (owner_user_id, workout_id),
        )
        return cursor.rowcount > 0


class ActiveWorkoutRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def set(self, *, user_id: str, workout_id: str, updated_at: datetime | str | None = None) -> None:
        self.connection.execute(
            """
            INSERT INTO active_workouts (
                user_id,
                workout_id,
                updated_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                workout_id = excluded.workout_id,
                updated_at = excluded.updated_at
            """,
            (user_id, workout_id, _timestamp(updated_at)),
        )

    def get(self, user_id: str) -> WorkoutRecord | None:
        row = self.connection.execute(
            """
            SELECT workouts.*
            FROM active_workouts
            JOIN workouts ON workouts.workout_id = active_workouts.workout_id
            WHERE active_workouts.user_id = ?
              AND workouts.owner_user_id = active_workouts.user_id
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        return _workout_from_row(row)


class WorkoutStreamsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def replace_for_workout(
        self,
        workout_id: str,
        *,
        points: tuple[WorkoutPointRecord, ...],
        streams: tuple[WorkoutStreamRecord, ...],
    ) -> None:
        self.connection.execute("DELETE FROM workout_points WHERE workout_id = ?", (workout_id,))
        self.connection.execute("DELETE FROM workout_streams WHERE workout_id = ?", (workout_id,))
        for point in points:
            if point.workout_id != workout_id:
                raise ValueError("Workout point workout_id does not match replacement workout_id")
            self.connection.execute(
                """
                INSERT INTO workout_points (
                    workout_id,
                    point_index,
                    timestamp_utc,
                    elapsed_s,
                    distance_m,
                    distance_km,
                    latitude,
                    longitude,
                    elevation_m,
                    heart_rate_bpm,
                    cadence_spm,
                    pace_s_per_km,
                    segment_index,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    point.workout_id,
                    point.point_index,
                    point.timestamp_utc,
                    point.elapsed_s,
                    point.distance_m,
                    point.distance_km,
                    point.latitude,
                    point.longitude,
                    point.elevation_m,
                    point.heart_rate_bpm,
                    point.cadence_spm,
                    point.pace_s_per_km,
                    point.segment_index,
                    _to_json(point.metadata),
                ),
            )
        for stream in streams:
            if stream.workout_id != workout_id:
                raise ValueError("Workout stream workout_id does not match replacement workout_id")
            self.connection.execute(
                """
                INSERT INTO workout_streams (
                    workout_id,
                    stream_key,
                    unit,
                    sample_count,
                    min_value,
                    max_value,
                    avg_value,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stream.workout_id,
                    stream.stream_key,
                    stream.unit,
                    stream.sample_count,
                    stream.min_value,
                    stream.max_value,
                    stream.avg_value,
                    _to_json(stream.metadata),
                ),
            )

    def list_points(self, workout_id: str) -> tuple[WorkoutPointRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM workout_points
            WHERE workout_id = ?
            ORDER BY point_index ASC
            """,
            (workout_id,),
        ).fetchall()
        return tuple(_workout_point_from_row(row) for row in rows)

    def list_streams(self, workout_id: str) -> tuple[WorkoutStreamRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM workout_streams
            WHERE workout_id = ?
            ORDER BY stream_key ASC
            """,
            (workout_id,),
        ).fetchall()
        return tuple(_workout_stream_from_row(row) for row in rows)


class RenderedArtifactsRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add(self, record: RenderedArtifactRecord) -> RenderedArtifactRecord:
        self.connection.execute(
            """
            INSERT INTO rendered_artifacts (
                artifact_id,
                owner_user_id,
                workflow_trace_id,
                artifact_type,
                filename,
                content_type,
                storage_path,
                created_at,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.artifact_id,
                record.owner_user_id,
                record.workflow_trace_id,
                record.artifact_type,
                record.filename,
                record.content_type,
                record.storage_path,
                record.created_at,
                _to_json(record.metadata),
            ),
        )
        return record

    def list_for_user(self, owner_user_id: str, *, limit: int = 20) -> tuple[RenderedArtifactRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM rendered_artifacts
            WHERE owner_user_id = ?
            ORDER BY created_at DESC, artifact_id DESC
            LIMIT ?
            """,
            (owner_user_id, limit),
        ).fetchall()
        return tuple(_rendered_artifact_from_row(row) for row in rows)


class DebugTraceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create(
        self,
        *,
        trace_id: str,
        source_event_id: str | None,
        workflow: str,
        status: str,
        started_at: datetime | str | None = None,
        payload: JsonObject | None = None,
    ) -> DebugTraceRecord:
        record = DebugTraceRecord(
            trace_id=trace_id,
            source_event_id=source_event_id,
            workflow=workflow,
            status=status,
            started_at=_timestamp(started_at),
            finished_at=None,
            payload=payload or {},
        )
        self.connection.execute(
            """
            INSERT INTO debug_traces (
                trace_id,
                source_event_id,
                workflow,
                status,
                started_at,
                finished_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.trace_id,
                record.source_event_id,
                record.workflow,
                record.status,
                record.started_at,
                record.finished_at,
                _to_json(record.payload),
            ),
        )
        return record

    def finish(self, trace_id: str, *, status: str, finished_at: datetime | str | None = None) -> None:
        self.connection.execute(
            """
            UPDATE debug_traces
            SET status = ?, finished_at = ?
            WHERE trace_id = ?
            """,
            (status, _timestamp(finished_at), trace_id),
        )

    def add_event(self, record: DebugTraceEventRecord) -> DebugTraceEventRecord:
        created_at = record.created_at or _timestamp(None)
        self.connection.execute(
            """
            INSERT INTO debug_trace_events (
                trace_event_id,
                trace_id,
                stage,
                level,
                message,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.trace_event_id,
                record.trace_id,
                record.stage,
                record.level,
                record.message,
                _to_json(record.payload),
                created_at,
            ),
        )
        if record.created_at:
            return record
        return DebugTraceEventRecord(
            trace_event_id=record.trace_event_id,
            trace_id=record.trace_id,
            stage=record.stage,
            level=record.level,
            message=record.message,
            payload=record.payload,
            created_at=created_at,
        )

    def get(self, trace_id: str) -> DebugTraceRecord | None:
        row = self.connection.execute(
            "SELECT * FROM debug_traces WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if row is None:
            return None
        return _debug_trace_from_row(row)

    def latest(self, *, exclude_trace_id: str | None = None) -> DebugTraceRecord | None:
        where = ""
        params: tuple[str, ...] = ()
        if exclude_trace_id is not None:
            where = "WHERE trace_id != ?"
            params = (exclude_trace_id,)
        row = self.connection.execute(
            f"""
            SELECT *
            FROM debug_traces
            {where}
            ORDER BY started_at DESC, trace_id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return _debug_trace_from_row(row)

    def latest_for_user(self, user_id: str, *, exclude_trace_id: str | None = None) -> DebugTraceRecord | None:
        where = "json_extract(payload_json, '$.user_id') = ?"
        params: tuple[str, ...] = (user_id,)
        if exclude_trace_id is not None:
            where = f"{where} AND trace_id != ?"
            params = (user_id, exclude_trace_id)
        row = self.connection.execute(
            f"""
            SELECT *
            FROM debug_traces
            WHERE {where}
            ORDER BY started_at DESC, trace_id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if row is None:
            return None
        return _debug_trace_from_row(row)

    def list_events(self, trace_id: str) -> tuple[DebugTraceEventRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM debug_trace_events
            WHERE trace_id = ?
            ORDER BY created_at ASC, trace_event_id ASC
            """,
            (trace_id,),
        ).fetchall()
        return tuple(_debug_trace_event_from_row(row) for row in rows)

    def prune_to_limit(self, *, keep: int) -> int:
        if keep <= 0:
            raise ValueError("keep must be positive")
        cursor = self.connection.execute(
            """
            DELETE FROM debug_traces
            WHERE trace_id IN (
                SELECT trace_id
                FROM debug_traces
                ORDER BY started_at DESC, trace_id DESC
                LIMIT -1 OFFSET ?
            )
            """,
            (keep,),
        )
        return cursor.rowcount


def _timestamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _to_json(value: JsonObject) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _from_json(value: str) -> JsonObject:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object")
    return parsed


def _user_from_row(row: sqlite3.Row) -> UserRecord:
    return UserRecord(
        user_id=row["user_id"],
        discord_user_name=row["discord_user_name"],
        discord_display_name=row["discord_display_name"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        last_seen_source=row["last_seen_source"],
        metadata=_from_json(row["metadata_json"]),
    )


def _channel_from_row(row: sqlite3.Row) -> ChannelRecord:
    return ChannelRecord(
        channel_id=row["channel_id"],
        guild_id=row["guild_id"],
        channel_name=row["channel_name"],
        metadata=_from_json(row["metadata_json"]),
    )


def _heart_rate_zone_from_row(row: sqlite3.Row) -> HeartRateZoneRecord:
    return HeartRateZoneRecord(
        user_id=row["user_id"],
        zone_key=row["zone_key"],
        label=row["label"],
        lower_bpm=row["lower_bpm"],
        upper_bpm=row["upper_bpm"],
        sort_order=row["sort_order"],
    )


def _history_from_row(row: sqlite3.Row) -> HistoryEventRecord:
    return HistoryEventRecord(
        history_id=row["history_id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        user_id=row["user_id"],
        role=row["role"],
        event_type=row["event_type"],
        content=row["content"],
        source_event_id=row["source_event_id"],
        created_at=row["created_at"],
        metadata=_from_json(row["metadata_json"]),
    )


def _attachment_from_row(row: sqlite3.Row) -> AttachmentRecord:
    return AttachmentRecord(
        attachment_id=row["attachment_id"],
        owner_user_id=row["owner_user_id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        filename=row["filename"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        raw_path=row["raw_path"],
        created_at=row["created_at"],
        metadata=_from_json(row["metadata_json"]),
    )


def _workout_from_row(row: sqlite3.Row) -> WorkoutRecord:
    return WorkoutRecord(
        workout_id=row["workout_id"],
        owner_user_id=row["owner_user_id"],
        source_attachment_id=row["source_attachment_id"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        title=row["title"],
        kind=row["kind"],
        primary_kind=row["primary_kind"],
        start_time_utc=row["start_time_utc"],
        start_time_local=row["start_time_local"],
        local_date=row["local_date"],
        distance_km=row["distance_km"],
        duration_s=row["duration_s"],
        pace_s_per_km=row["pace_s_per_km"],
        ascent_m=row["ascent_m"],
        avg_hr_bpm=row["avg_hr_bpm"],
        max_hr_bpm=row["max_hr_bpm"],
        point_count=row["point_count"],
        created_at=row["created_at"],
        schema_version=row["schema_version"],
        metadata=_from_json(row["metadata_json"]),
    )


def _workout_point_from_row(row: sqlite3.Row) -> WorkoutPointRecord:
    return WorkoutPointRecord(
        workout_id=row["workout_id"],
        point_index=row["point_index"],
        timestamp_utc=row["timestamp_utc"],
        elapsed_s=row["elapsed_s"],
        distance_m=row["distance_m"],
        distance_km=row["distance_km"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        elevation_m=row["elevation_m"],
        heart_rate_bpm=row["heart_rate_bpm"],
        cadence_spm=row["cadence_spm"],
        pace_s_per_km=row["pace_s_per_km"],
        segment_index=row["segment_index"],
        metadata=_from_json(row["metadata_json"]),
    )


def _workout_stream_from_row(row: sqlite3.Row) -> WorkoutStreamRecord:
    return WorkoutStreamRecord(
        workout_id=row["workout_id"],
        stream_key=row["stream_key"],
        unit=row["unit"],
        sample_count=row["sample_count"],
        min_value=row["min_value"],
        max_value=row["max_value"],
        avg_value=row["avg_value"],
        metadata=_from_json(row["metadata_json"]),
    )


def _rendered_artifact_from_row(row: sqlite3.Row) -> RenderedArtifactRecord:
    return RenderedArtifactRecord(
        artifact_id=row["artifact_id"],
        owner_user_id=row["owner_user_id"],
        workflow_trace_id=row["workflow_trace_id"],
        artifact_type=row["artifact_type"],
        filename=row["filename"],
        content_type=row["content_type"],
        storage_path=row["storage_path"],
        created_at=row["created_at"],
        metadata=_from_json(row["metadata_json"]),
    )


def _debug_trace_from_row(row: sqlite3.Row) -> DebugTraceRecord:
    return DebugTraceRecord(
        trace_id=row["trace_id"],
        source_event_id=row["source_event_id"],
        workflow=row["workflow"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        payload=_from_json(row["payload_json"]),
    )


def _debug_trace_event_from_row(row: sqlite3.Row) -> DebugTraceEventRecord:
    return DebugTraceEventRecord(
        trace_event_id=row["trace_event_id"],
        trace_id=row["trace_id"],
        stage=row["stage"],
        level=row["level"],
        message=row["message"],
        payload=_from_json(row["payload_json"]),
        created_at=row["created_at"],
    )
