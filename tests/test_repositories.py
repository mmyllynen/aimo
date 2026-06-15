from __future__ import annotations

import sqlite3
import unittest

from storage.repositories import (
    ActiveWorkoutRepository,
    AttachmentRecord,
    AttachmentsRepository,
    ChannelsRepository,
    DebugTraceEventRecord,
    DebugTraceRepository,
    HeartRateZoneRecord,
    HeartRateZonesRepository,
    HistoryEventRecord,
    HistoryRepository,
    RenderedArtifactRecord,
    RenderedArtifactsRepository,
    UsersRepository,
    WorkoutPointRecord,
    WorkoutRecord,
    WorkoutStreamRecord,
    WorkoutStreamsRepository,
    WorkoutsRepository,
)
from storage.sqlite import load_schema, open_connection, transaction


class RepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_connection()
        load_schema(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_users_touch_creates_and_updates_last_seen_without_overwriting_first_seen(self) -> None:
        users = UsersRepository(self.connection)

        with transaction(self.connection):
            first = users.touch(
                user_id="user-1",
                discord_user_name="runner",
                discord_display_name="Runner",
                seen_at="2026-06-13T10:00:00Z",
                source="mention",
                metadata={"timezone": "Europe/Helsinki"},
            )
            second = users.touch(
                user_id="user-1",
                discord_user_name="runner2",
                discord_display_name="Runner Two",
                seen_at="2026-06-13T11:00:00Z",
                source="slash",
                metadata={"timezone": "UTC"},
            )

        self.assertEqual(first.first_seen_at, "2026-06-13T10:00:00Z")
        self.assertEqual(second.first_seen_at, "2026-06-13T10:00:00Z")
        self.assertEqual(second.last_seen_at, "2026-06-13T11:00:00Z")
        self.assertEqual(second.last_seen_source, "slash")
        self.assertEqual(second.discord_display_name, "Runner Two")
        self.assertEqual(second.metadata["timezone"], "UTC")

    def test_channels_upsert_round_trips_metadata(self) -> None:
        channels = ChannelsRepository(self.connection)

        with transaction(self.connection):
            record = channels.upsert(
                channel_id="channel-1",
                guild_id="guild-1",
                channel_name="training",
                metadata={"kind": "text"},
            )

        self.assertEqual(record.channel_id, "channel-1")
        self.assertEqual(record.guild_id, "guild-1")
        self.assertEqual(record.metadata["kind"], "text")
        self.assertEqual(channels.get("channel-1"), record)

    def test_heart_rate_zones_replace_for_user(self) -> None:
        users = UsersRepository(self.connection)
        zones = HeartRateZonesRepository(self.connection)

        with transaction(self.connection):
            users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            zones.replace_for_user(
                "user-1",
                (
                    HeartRateZoneRecord(
                        user_id="user-1",
                        zone_key="z2",
                        label="Zone 2",
                        lower_bpm=120,
                        upper_bpm=139,
                        sort_order=2,
                    ),
                    HeartRateZoneRecord(
                        user_id="user-1",
                        zone_key="z1",
                        label="Zone 1",
                        lower_bpm=None,
                        upper_bpm=119,
                        sort_order=1,
                    ),
                ),
            )

        stored = zones.list_for_user("user-1")

        self.assertEqual([zone.zone_key for zone in stored], ["z1", "z2"])
        self.assertEqual(stored[1].lower_bpm, 120)

    def test_history_recent_for_channel_returns_bounded_chronological_records(self) -> None:
        users = UsersRepository(self.connection)
        channels = ChannelsRepository(self.connection)
        history = HistoryRepository(self.connection)

        with transaction(self.connection):
            users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            channels.upsert(channel_id="channel-1", guild_id="guild-1")
            channels.upsert(channel_id="channel-2", guild_id="guild-1")
            for index in range(4):
                history.add(
                    HistoryEventRecord(
                        history_id=f"history-{index}",
                        guild_id="guild-1",
                        channel_id="channel-1",
                        user_id="user-1",
                        role="user",
                        event_type="message",
                        content=f"message {index}",
                        source_event_id=f"event-{index}",
                        created_at=f"2026-06-13T10:0{index}:00Z",
                    )
                )
            history.add(
                HistoryEventRecord(
                    history_id="other-channel",
                    guild_id="guild-1",
                    channel_id="channel-2",
                    user_id="user-1",
                    role="user",
                    event_type="message",
                    content="wrong channel",
                    source_event_id="event-other",
                    created_at="2026-06-13T10:10:00Z",
                )
            )

        recent = history.list_recent_for_channel("channel-1", limit=2)

        self.assertEqual([record.content for record in recent], ["message 2", "message 3"])

    def test_attachments_find_duplicate_by_owner_and_hash(self) -> None:
        users = UsersRepository(self.connection)
        attachments = AttachmentsRepository(self.connection)

        with transaction(self.connection):
            users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            attachments.add(
                AttachmentRecord(
                    attachment_id="attachment-1",
                    owner_user_id="user-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    message_id="message-1",
                    filename="run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=100,
                    sha256="same-hash",
                    raw_path="raw/attachment-1.gpx",
                    created_at="2026-06-13T10:00:00Z",
                    metadata={"source": "test"},
                )
            )
            attachments.add(
                AttachmentRecord(
                    attachment_id="attachment-2",
                    owner_user_id="user-2",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    message_id="message-2",
                    filename="run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=100,
                    sha256="same-hash",
                    raw_path="raw/attachment-2.gpx",
                    created_at="2026-06-13T10:01:00Z",
                )
            )

        duplicate = attachments.find_by_sha256("user-1", "same-hash")

        self.assertEqual(duplicate.attachment_id, "attachment-1")
        self.assertEqual(duplicate.metadata["source"], "test")
        self.assertEqual(attachments.get("attachment-2").owner_user_id, "user-2")

    def test_workouts_are_user_owned_and_latest_is_per_user(self) -> None:
        self._seed_two_user_workouts()
        workouts = WorkoutsRepository(self.connection)

        user_one_workouts = workouts.list_for_user("user-1")
        user_two_workouts = workouts.list_for_user("user-2")
        latest = workouts.latest_for_user("user-1")

        self.assertEqual([workout.workout_id for workout in user_one_workouts], ["workout-2", "workout-1"])
        self.assertEqual([workout.workout_id for workout in user_two_workouts], ["workout-3"])
        self.assertEqual(latest.workout_id, "workout-2")
        self.assertIsNone(workouts.get_for_user("user-2", "workout-1"))

    def test_active_workout_returns_only_user_owned_workout(self) -> None:
        self._seed_two_user_workouts()
        active = ActiveWorkoutRepository(self.connection)

        with transaction(self.connection):
            active.set(
                user_id="user-1",
                workout_id="workout-2",
                updated_at="2026-06-13T12:00:00Z",
            )

        workout = active.get("user-1")

        self.assertEqual(workout.workout_id, "workout-2")
        self.assertEqual(workout.owner_user_id, "user-1")

    def test_workout_streams_replace_points_and_stream_summaries(self) -> None:
        self._seed_two_user_workouts()
        streams = WorkoutStreamsRepository(self.connection)

        with transaction(self.connection):
            streams.replace_for_workout(
                "workout-1",
                points=(
                    WorkoutPointRecord(
                        workout_id="workout-1",
                        point_index=0,
                        elapsed_s=0.0,
                        distance_km=0.0,
                        heart_rate_bpm=120,
                    ),
                    WorkoutPointRecord(
                        workout_id="workout-1",
                        point_index=1,
                        elapsed_s=60.0,
                        distance_km=0.2,
                        heart_rate_bpm=130,
                    ),
                ),
                streams=(
                    WorkoutStreamRecord(
                        workout_id="workout-1",
                        stream_key="heart_rate",
                        unit="bpm",
                        sample_count=2,
                        min_value=120,
                        max_value=130,
                        avg_value=125,
                    ),
                ),
            )

        points = streams.list_points("workout-1")
        summaries = streams.list_streams("workout-1")

        self.assertEqual([point.point_index for point in points], [0, 1])
        self.assertEqual(points[1].heart_rate_bpm, 130)
        self.assertEqual(summaries[0].stream_key, "heart_rate")
        self.assertEqual(summaries[0].avg_value, 125)

    def test_rendered_artifacts_are_listed_per_owner(self) -> None:
        users = UsersRepository(self.connection)
        artifacts = RenderedArtifactsRepository(self.connection)

        with transaction(self.connection):
            users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            artifacts.add(
                RenderedArtifactRecord(
                    artifact_id="artifact-1",
                    owner_user_id="user-1",
                    workflow_trace_id=None,
                    artifact_type="chart",
                    filename="chart.png",
                    content_type="image/png",
                    storage_path="artifacts/chart.png",
                    created_at="2026-06-13T10:00:00Z",
                    metadata={"workout_id": "workout-1"},
                )
            )
            artifacts.add(
                RenderedArtifactRecord(
                    artifact_id="artifact-2",
                    owner_user_id="user-2",
                    workflow_trace_id=None,
                    artifact_type="chart",
                    filename="chart.png",
                    content_type="image/png",
                    storage_path="artifacts/chart-2.png",
                    created_at="2026-06-13T10:01:00Z",
                )
            )

        user_one_artifacts = artifacts.list_for_user("user-1")

        self.assertEqual(len(user_one_artifacts), 1)
        self.assertEqual(user_one_artifacts[0].artifact_id, "artifact-1")
        self.assertEqual(user_one_artifacts[0].metadata["workout_id"], "workout-1")

    def test_debug_trace_repository_tracks_trace_lifecycle_and_events(self) -> None:
        traces = DebugTraceRepository(self.connection)

        with transaction(self.connection):
            traces.create(
                trace_id="trace-1",
                source_event_id="event-1",
                workflow="help",
                status="started",
                started_at="2026-06-13T10:00:00Z",
                payload={"route": "help"},
            )
            traces.add_event(
                DebugTraceEventRecord(
                    trace_event_id="trace-event-1",
                    trace_id="trace-1",
                    stage="route",
                    level="info",
                    message="routed",
                    payload={"confidence": "high"},
                    created_at="2026-06-13T10:00:01Z",
                )
            )
            traces.add_event(
                DebugTraceEventRecord(
                    trace_event_id="trace-event-2",
                    trace_id="trace-1",
                    stage="reply",
                    level="debug",
                    message="reply created",
                    created_at="2026-06-13T10:00:02Z",
                )
            )
            traces.finish(
                "trace-1",
                status="success",
                finished_at="2026-06-13T10:00:03Z",
            )

        trace = traces.get("trace-1")
        events = traces.list_events("trace-1")
        latest = traces.latest()

        self.assertEqual(trace.status, "success")
        self.assertEqual(trace.payload["route"], "help")
        self.assertEqual(trace.finished_at, "2026-06-13T10:00:03Z")
        self.assertEqual([event.stage for event in events], ["route", "reply"])
        self.assertEqual(events[0].payload["confidence"], "high")
        self.assertEqual(latest.trace_id, "trace-1")

    def test_repository_operations_participate_in_outer_transaction(self) -> None:
        users = UsersRepository(self.connection)
        traces = DebugTraceRepository(self.connection)

        with self.assertRaises(sqlite3.IntegrityError):
            with transaction(self.connection):
                users.touch(user_id="user-1", seen_at="2026-06-13T10:00:00Z")
                traces.add_event(
                    DebugTraceEventRecord(
                        trace_event_id="orphan-event",
                        trace_id="missing-trace",
                        stage="route",
                        level="error",
                        message="should rollback",
                        created_at="2026-06-13T10:00:01Z",
                    )
                )

        self.assertIsNone(users.get("user-1"))

    def test_delete_workout_is_scoped_to_owner_and_cascades_streams(self) -> None:
        self._seed_two_user_workouts()
        workouts = WorkoutsRepository(self.connection)
        streams = WorkoutStreamsRepository(self.connection)

        with transaction(self.connection):
            streams.replace_for_workout(
                "workout-1",
                points=(WorkoutPointRecord(workout_id="workout-1", point_index=0),),
                streams=(WorkoutStreamRecord(workout_id="workout-1", stream_key="heart_rate"),),
            )
            wrong_owner_deleted = workouts.delete_for_user("user-2", "workout-1")
            right_owner_deleted = workouts.delete_for_user("user-1", "workout-1")

        self.assertFalse(wrong_owner_deleted)
        self.assertTrue(right_owner_deleted)
        self.assertIsNone(workouts.get_for_user("user-1", "workout-1"))
        self.assertEqual(streams.list_points("workout-1"), ())
        self.assertEqual(streams.list_streams("workout-1"), ())

    def _seed_two_user_workouts(self) -> None:
        users = UsersRepository(self.connection)
        attachments = AttachmentsRepository(self.connection)
        workouts = WorkoutsRepository(self.connection)

        with transaction(self.connection):
            users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            attachments.add(
                AttachmentRecord(
                    attachment_id="attachment-1",
                    owner_user_id="user-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    message_id="message-1",
                    filename="run-1.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=100,
                    sha256="hash-1",
                    raw_path="raw/run-1.gpx",
                    created_at="2026-06-13T09:30:00Z",
                )
            )
            for workout in (
                WorkoutRecord(
                    workout_id="workout-1",
                    owner_user_id="user-1",
                    source_attachment_id="attachment-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Morning run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T07:00:00Z",
                    start_time_local="2026-06-13T10:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=5.0,
                    duration_s=1800,
                    pace_s_per_km=360,
                    ascent_m=20,
                    avg_hr_bpm=130,
                    max_hr_bpm=150,
                    point_count=2,
                    created_at="2026-06-13T10:30:00Z",
                    metadata={"source": "test"},
                ),
                WorkoutRecord(
                    workout_id="workout-2",
                    owner_user_id="user-1",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Evening run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T16:00:00Z",
                    start_time_local="2026-06-13T19:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=6.0,
                    duration_s=2100,
                    pace_s_per_km=350,
                    ascent_m=30,
                    avg_hr_bpm=132,
                    max_hr_bpm=152,
                    point_count=0,
                    created_at="2026-06-13T19:40:00Z",
                ),
                WorkoutRecord(
                    workout_id="workout-3",
                    owner_user_id="user-2",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Other user run",
                    kind="run",
                    primary_kind="run",
                    start_time_utc="2026-06-13T17:00:00Z",
                    start_time_local="2026-06-13T20:00:00+03:00",
                    local_date="2026-06-13",
                    distance_km=4.0,
                    duration_s=1500,
                    pace_s_per_km=375,
                    ascent_m=15,
                    avg_hr_bpm=125,
                    max_hr_bpm=145,
                    point_count=0,
                    created_at="2026-06-13T20:30:00Z",
                ),
            ):
                workouts.add(workout)


if __name__ == "__main__":
    unittest.main()
