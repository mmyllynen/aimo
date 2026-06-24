from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL

from storage.repositories import (
    AttachmentRecord,
    WorkoutPointRecord,
    WorkoutRecord,
    WorkoutStreamRecord,
)
from storage.files import write_bytes_under
from storage.unit_of_work import RepositoryBundle
from workout.estimate_features import upsert_workout_estimate_features
from workout.gpx import GpxParseError, ParsedGpxWorkout, parse_gpx


GPX_CONTENT_TYPES = {
    "application/gpx+xml",
    "application/xml",
    "text/xml",
    "application/octet-stream",
}


class GpxIngestError(ValueError):
    pass


class UnsupportedAttachmentError(GpxIngestError):
    pass


class InvalidGpxError(GpxIngestError):
    pass


@dataclass(frozen=True)
class GpxIngestRequest:
    owner_user_id: str
    guild_id: str | None
    channel_id: str | None
    message_id: str | None
    attachment_id: str
    filename: str
    content_type: str
    content: bytes
    created_at: datetime
    max_size_bytes: int
    make_active: bool = True
    title_override: str = ""
    raw_storage_root: Path | None = None


@dataclass(frozen=True)
class GpxIngestResult:
    status: str
    workout: WorkoutRecord | None = None
    duplicate_of_workout_id: str = ""

    @property
    def duplicate(self) -> bool:
        return self.status == "duplicate"


def ingest_gpx(request: GpxIngestRequest, repositories: RepositoryBundle) -> GpxIngestResult:
    _validate_attachment(request)
    sha256 = hashlib.sha256(request.content).hexdigest()
    duplicate_attachment = repositories.attachments.find_by_sha256(request.owner_user_id, sha256)
    if duplicate_attachment is not None:
        duplicate_workout = repositories.workouts.find_by_source_attachment(
            request.owner_user_id,
            duplicate_attachment.attachment_id,
        )
        if duplicate_workout is None:
            return _create_workout_for_attachment(request, repositories, duplicate_attachment.attachment_id)
        duplicate_workout = _refresh_duplicate_workout(request, repositories, duplicate_workout)
        return GpxIngestResult(
            status="duplicate",
            workout=duplicate_workout,
            duplicate_of_workout_id=duplicate_workout.workout_id if duplicate_workout else "",
        )

    try:
        parsed = parse_gpx(request.content, fallback_title=request.filename)
    except GpxParseError as exc:
        raise InvalidGpxError(str(exc)) from exc

    timestamp = _timestamp(request.created_at)
    raw_relative_path = Path(f"{sha256}.gpx")
    raw_path = str(raw_relative_path)
    metadata = {"storage_status": "not_written_in_skeleton"}
    if request.raw_storage_root is not None:
        stored_path = write_bytes_under(request.raw_storage_root, raw_relative_path, request.content)
        raw_path = str(stored_path)
        metadata = {"storage_status": "written"}
    attachment = repositories.attachments.add(
        AttachmentRecord(
            attachment_id=request.attachment_id,
            owner_user_id=request.owner_user_id,
            guild_id=request.guild_id,
            channel_id=request.channel_id,
            message_id=request.message_id,
            filename=request.filename,
            content_type=request.content_type,
            size_bytes=len(request.content),
            sha256=sha256,
            raw_path=raw_path,
            created_at=timestamp,
            metadata=metadata,
        )
    )
    workout = repositories.workouts.add(_workout_record(request, attachment.attachment_id, parsed, timestamp))
    _replace_streams_and_features(repositories, workout, parsed, updated_at=request.created_at)
    if request.make_active:
        repositories.active_workouts.set(
            user_id=request.owner_user_id,
            workout_id=workout.workout_id,
            updated_at=request.created_at,
        )
    return GpxIngestResult(status="created", workout=workout)


def _create_workout_for_attachment(
    request: GpxIngestRequest,
    repositories: RepositoryBundle,
    attachment_id: str,
) -> GpxIngestResult:
    try:
        parsed = parse_gpx(request.content, fallback_title=request.filename)
    except GpxParseError as exc:
        raise InvalidGpxError(str(exc)) from exc

    workout = repositories.workouts.add(_workout_record(request, attachment_id, parsed, _timestamp(request.created_at)))
    _replace_streams_and_features(repositories, workout, parsed, updated_at=request.created_at)
    if request.make_active:
        repositories.active_workouts.set(
            user_id=request.owner_user_id,
            workout_id=workout.workout_id,
            updated_at=request.created_at,
        )
    return GpxIngestResult(status="created", workout=workout)


def _replace_streams_and_features(
    repositories: RepositoryBundle,
    workout: WorkoutRecord,
    parsed: ParsedGpxWorkout,
    *,
    updated_at: datetime,
) -> None:
    points = _point_records(workout.workout_id, parsed)
    repositories.workout_streams.replace_for_workout(
        workout.workout_id,
        points=points,
        streams=_stream_records(workout.workout_id, parsed),
    )
    upsert_workout_estimate_features(repositories, workout, points, updated_at=updated_at)


def _refresh_duplicate_workout(
    request: GpxIngestRequest,
    repositories: RepositoryBundle,
    duplicate_workout: WorkoutRecord,
) -> WorkoutRecord:
    try:
        parsed = parse_gpx(request.content, fallback_title=request.filename)
    except GpxParseError as exc:
        raise InvalidGpxError(str(exc)) from exc
    refreshed = WorkoutRecord(
        workout_id=duplicate_workout.workout_id,
        owner_user_id=duplicate_workout.owner_user_id,
        source_attachment_id=duplicate_workout.source_attachment_id,
        guild_id=duplicate_workout.guild_id,
        channel_id=duplicate_workout.channel_id,
        title=duplicate_workout.title,
        kind=parsed.kind,
        primary_kind=parsed.primary_kind,
        start_time_utc=parsed.start_time_utc,
        start_time_local=parsed.start_time_local,
        local_date=parsed.local_date,
        distance_km=parsed.distance_km,
        duration_s=parsed.duration_s,
        pace_s_per_km=parsed.pace_s_per_km,
        ascent_m=parsed.ascent_m,
        avg_hr_bpm=parsed.avg_hr_bpm,
        max_hr_bpm=parsed.max_hr_bpm,
        point_count=len(parsed.points),
        created_at=duplicate_workout.created_at,
        schema_version=duplicate_workout.schema_version,
        metadata=parsed.metadata,
    )
    repositories.workouts.update_derived_fields(refreshed)
    _replace_streams_and_features(repositories, refreshed, parsed, updated_at=request.created_at)
    return refreshed


def is_supported_gpx_attachment(filename: str, content_type: str) -> bool:
    normalized_type = content_type.strip().lower()
    return filename.lower().endswith(".gpx") or normalized_type in GPX_CONTENT_TYPES


def _validate_attachment(request: GpxIngestRequest) -> None:
    if request.max_size_bytes <= 0:
        raise ValueError("max_size_bytes must be positive")
    if len(request.content) > request.max_size_bytes:
        raise UnsupportedAttachmentError("Attachment is too large")
    if not is_supported_gpx_attachment(request.filename, request.content_type):
        raise UnsupportedAttachmentError("Attachment is not GPX")
    if not request.content:
        raise InvalidGpxError("Attachment is empty")


def _workout_record(
    request: GpxIngestRequest,
    source_attachment_id: str,
    parsed: ParsedGpxWorkout,
    created_at: str,
) -> WorkoutRecord:
    workout_id = _stable_workout_id(request.owner_user_id, source_attachment_id)
    return WorkoutRecord(
        workout_id=workout_id,
        owner_user_id=request.owner_user_id,
        source_attachment_id=source_attachment_id,
        guild_id=request.guild_id,
        channel_id=request.channel_id,
        title=request.title_override or parsed.title,
        kind=parsed.kind,
        primary_kind=parsed.primary_kind,
        start_time_utc=parsed.start_time_utc,
        start_time_local=parsed.start_time_local,
        local_date=parsed.local_date,
        distance_km=parsed.distance_km,
        duration_s=parsed.duration_s,
        pace_s_per_km=parsed.pace_s_per_km,
        ascent_m=parsed.ascent_m,
        avg_hr_bpm=parsed.avg_hr_bpm,
        max_hr_bpm=parsed.max_hr_bpm,
        point_count=len(parsed.points),
        created_at=created_at,
        metadata=parsed.metadata,
    )


def _point_records(workout_id: str, parsed: ParsedGpxWorkout) -> tuple[WorkoutPointRecord, ...]:
    return tuple(
        WorkoutPointRecord(
            workout_id=workout_id,
            point_index=point.point_index,
            timestamp_utc=point.timestamp_utc,
            elapsed_s=point.elapsed_s,
            distance_m=point.distance_m,
            distance_km=point.distance_km,
            latitude=point.latitude,
            longitude=point.longitude,
            elevation_m=point.elevation_m,
            heart_rate_bpm=point.heart_rate_bpm,
            cadence_spm=point.cadence_spm,
            pace_s_per_km=point.pace_s_per_km,
            segment_index=point.segment_index,
        )
        for point in parsed.points
    )


def _stream_records(workout_id: str, parsed: ParsedGpxWorkout) -> tuple[WorkoutStreamRecord, ...]:
    return tuple(
        WorkoutStreamRecord(
            workout_id=workout_id,
            stream_key=stream.stream_key,
            unit=stream.unit,
            sample_count=stream.sample_count,
            min_value=stream.min_value,
            max_value=stream.max_value,
            avg_value=stream.avg_value,
        )
        for stream in parsed.streams
    )


def _stable_workout_id(owner_user_id: str, attachment_id: str) -> str:
    return f"workout-{uuid5(NAMESPACE_URL, f'aimo:{owner_user_id}:{attachment_id}')}"


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
