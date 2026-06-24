from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import tempfile
import unittest
from pathlib import Path

from app.dispatcher import DispatchContext, Dispatcher
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource
from core.i18n import TranslationKey
from core.routing import WorkflowTarget
from core.workflows import WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from storage.repositories import AttachmentRecord, WorkoutRecord
from storage.unit_of_work import UnitOfWork, open_database
from workout.estimate_features import backfill_workout_estimate_features
from workout.gpx import GpxParseError, parse_gpx


SAMPLE_GPX = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="aimo-test" xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
  <metadata><name>Morning Run</name></metadata>
  <trk>
    <name>Track Name</name>
    <trkseg>
      <trkpt lat="60.16990" lon="24.93840">
        <ele>10</ele>
        <time>2026-06-13T06:00:00Z</time>
        <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>120</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
      </trkpt>
      <trkpt lat="60.17090" lon="24.93940">
        <ele>16</ele>
        <time>2026-06-13T06:05:00Z</time>
        <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>130</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
      </trkpt>
      <trkpt lat="60.17190" lon="24.94040">
        <ele>14</ele>
        <time>2026-06-13T06:10:00Z</time>
        <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>
      </trkpt>
    </trkseg>
  </trk>
</gpx>
"""

COURSE_GPX = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="aimo-test" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>Lohja 24km</name></metadata>
  <wpt lat="61.000000" lon="25.000000"><name>Info</name><cmt>Course point</cmt><type>INFO</type></wpt>
  <trk>
    <name>Lohja 24km</name>
    <trkseg>
      <trkpt lat="60.000000" lon="24.000000"><ele>10</ele></trkpt>
      <trkpt lat="60.010000" lon="24.000000"><ele>20</ele></trkpt>
      <trkpt lat="60.020000" lon="24.000000"><ele>15</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


class GpxParserTests(unittest.TestCase):
    def test_parse_gpx_derives_workout_summary_points_and_streams(self) -> None:
        parsed = parse_gpx(SAMPLE_GPX, fallback_title="fallback.gpx")

        self.assertEqual(parsed.title, "Morning Run")
        self.assertEqual(parsed.kind, "activity")
        self.assertEqual(parsed.primary_kind, "activity")
        self.assertEqual(parsed.start_time_utc, "2026-06-13T06:00:00Z")
        self.assertEqual(parsed.start_time_local, "2026-06-13T09:00:00+03:00")
        self.assertEqual(parsed.local_date, "2026-06-13")
        self.assertEqual(parsed.duration_s, 600)
        self.assertEqual(len(parsed.points), 3)
        self.assertGreater(parsed.distance_km, 0)
        self.assertEqual(parsed.ascent_m, 6)
        self.assertEqual(parsed.avg_hr_bpm, 130)
        self.assertEqual(parsed.max_hr_bpm, 140)
        stream_keys = {stream.stream_key for stream in parsed.streams}
        self.assertIn("heart_rate", stream_keys)
        self.assertIn("distance", stream_keys)

    def test_parse_gpx_track_without_activity_data_is_route_plan_and_excludes_waypoints_from_distance(self) -> None:
        parsed = parse_gpx(COURSE_GPX, fallback_title="course.gpx")

        self.assertEqual(parsed.kind, "route_plan")
        self.assertEqual(parsed.primary_kind, "route")
        self.assertIsNone(parsed.local_date)
        self.assertIsNone(parsed.duration_s)
        self.assertEqual(len(parsed.points), 3)
        self.assertEqual(parsed.metadata["track_point_count"], 3)
        self.assertEqual(parsed.metadata["waypoint_count"], 1)
        self.assertEqual(parsed.metadata["waypoints"], [{"latitude": 61.0, "longitude": 25.0, "name": "Info", "comment": "Course point", "type": "INFO"}])
        self.assertEqual(parsed.waypoints[0].name, "Info")
        self.assertEqual(parsed.waypoints[0].comment, "Course point")
        self.assertEqual(parsed.waypoints[0].waypoint_type, "INFO")
        self.assertLess(parsed.distance_km or 0.0, 3.0)

    def test_parse_gpx_filters_small_elevation_noise_from_ascent(self) -> None:
        gpx = _gpx_with_elevations(
            (10.0, 10.8, 10.1, 11.2, 10.2, 13.6, 14.1, 10.7, 13.8),
        )

        parsed = parse_gpx(gpx, fallback_title="noise.gpx")

        self.assertAlmostEqual(parsed.ascent_m or 0.0, 7.2, places=6)

    def test_latest_downloaded_activity_ascent_matches_deadband_model(self) -> None:
        path = Path.home() / "Downloads" / "activity_23264644106.gpx"
        if not path.exists():
            self.skipTest("local Garmin sample is not available")

        parsed = parse_gpx(path.read_bytes(), fallback_title=path.name)

        self.assertAlmostEqual(parsed.ascent_m or 0.0, 65.6, places=1)

    def test_parse_gpx_rejects_invalid_xml(self) -> None:
        with self.assertRaises(GpxParseError):
            parse_gpx(b"<not-gpx />")


class GpxIngestWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_gpx_attachment_dispatch_ingests_workout_and_sets_active(self) -> None:
        event = _gpx_event("event-1", "attachment-1", SAMPLE_GPX)

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.GPX_ACCEPTED)
        self.assertEqual(result.messages[0].localized_text.params["title"], "Morning Run")
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")
            active = repositories.active_workouts.get("user-1")
            points = repositories.workout_streams.list_points(workouts[0].workout_id)
            streams = repositories.workout_streams.list_streams(workouts[0].workout_id)
            features = repositories.workout_estimate_features.get(workouts[0].workout_id)

        self.assertEqual(len(workouts), 1)
        self.assertEqual(active.workout_id, workouts[0].workout_id)
        self.assertEqual(len(points), 3)
        self.assertIn("heart_rate", {stream.stream_key for stream in streams})
        self.assertIsNotNone(features)
        self.assertEqual(features.owner_user_id, "user-1")
        self.assertEqual(features.feature_version, 1)
        self.assertGreater(features.distance_km or 0.0, 0.0)
        self.assertEqual(features.ascent_m, 6)
        self.assertIn("low_point_count", features.quality_flags)
        self.assertIn("location", features.metadata)
        self.assertAlmostEqual(features.metadata["location"]["centroid_latitude"], 60.1709, places=3)

    def test_route_plan_gpx_feedback_says_route(self) -> None:
        event = _gpx_event("event-1", "attachment-1", COURSE_GPX)

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.GPX_ACCEPTED_ROUTE)
        self.assertEqual(result.messages[0].localized_text.params["title"], "Lohja 24km")
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].primary_kind, "route")

    def test_multiple_gpx_attachments_dispatch_ingests_each_workout(self) -> None:
        second_gpx = SAMPLE_GPX.replace(b"Morning Run", b"Evening Run").replace(
            b"2026-06-13T06:",
            b"2026-06-14T18:",
        )
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            extra_attachments=(
                AttachmentRef(
                    attachment_id="attachment-2",
                    filename="evening-run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=len(second_gpx),
                    metadata={"content": second_gpx},
                ),
            ),
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual([message.localized_text.key for message in result.messages], [TranslationKey.GPX_ACCEPTED] * 2)
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")
            active = repositories.active_workouts.get("user-1")

        self.assertEqual(len(workouts), 2)
        self.assertEqual({workout.title for workout in workouts}, {"Morning Run", "Evening Run"})
        self.assertEqual(active.title, "Evening Run")

    def test_single_mention_gpx_can_set_title_with_finnish_tarkenne(self) -> None:
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text='tallenna tämä treeni nimi="Aamulenkki 18.6."',
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].localized_text.params["title"], "Aamulenkki 18.6.")
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].title, "Aamulenkki 18.6.")

    def test_single_mention_gpx_can_set_title_with_english_tarkenne(self) -> None:
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text='save this workout name="Morning run 18.6."',
        )

        result = self.dispatcher.dispatch(event, DispatchContext(UnitOfWork(self.connection)))

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].title, "Morning run 18.6.")

    def test_single_mention_gpx_can_set_title_from_llm_when_no_tarkenne(self) -> None:
        client = FakeLLMClient({LLMOperation.GPX_TITLE_EXTRACTION: {"title": "Aamulenkki 18.6."}})
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text='tallenna tämä treeni ja anna sille nimeksi "Aamulenkki 18.6."',
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(client.requests[0].operation, LLMOperation.GPX_TITLE_EXTRACTION)
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].title, "Aamulenkki 18.6.")

    def test_single_mention_gpx_tarkenne_wins_over_llm_title(self) -> None:
        client = FakeLLMClient({LLMOperation.GPX_TITLE_EXTRACTION: {"title": "Mallin nimi"}})
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text='tallenna tämä nimi="Tarkenteen nimi"',
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(client.requests, [])
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].title, "Tarkenteen nimi")

    def test_multiple_gpx_attachments_ignore_title_tarkenne_and_llm_title(self) -> None:
        second_gpx = SAMPLE_GPX.replace(b"Morning Run", b"Evening Run").replace(
            b"2026-06-13T06:",
            b"2026-06-14T18:",
        )
        client = FakeLLMClient({LLMOperation.GPX_TITLE_EXTRACTION: {"title": "Yhteinen nimi"}})
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text='tallenna nämä nimi="Yhteinen nimi"',
            extra_attachments=(
                AttachmentRef(
                    attachment_id="attachment-2",
                    filename="evening-run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=len(second_gpx),
                    metadata={"content": second_gpx},
                ),
            ),
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(client.requests, [])
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual({workout.title for workout in workouts}, {"Morning Run", "Evening Run"})

    def test_slash_gpx_upload_uses_optional_title_without_llm(self) -> None:
        client = FakeLLMClient({LLMOperation.GPX_TITLE_EXTRACTION: {"title": "Slash title"}})
        event = _gpx_event(
            "event-1",
            "attachment-1",
            SAMPLE_GPX,
            text="/gpx tallenna",
            kind=EventKind.SLASH_COMMAND,
            source=EventSource.DISCORD_SLASH,
            metadata={
                "command_name": "gpx",
                "subcommand": "tallenna",
                "options": {"liite": "attachment-1", "nimi": "Slash title"},
            },
        )

        result = self.dispatcher.dispatch(
            event,
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(client.requests, [])
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(workouts[0].title, "Slash title")

    def test_gpx_ingest_writes_raw_file_when_storage_root_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            event = _gpx_event("event-1", "attachment-1", SAMPLE_GPX)

            result = self.dispatcher.dispatch(
                event,
                DispatchContext(UnitOfWork(self.connection), raw_gpx_path=Path(tmpdir)),
            )

            self.assertEqual(result.status, WorkflowStatus.SUCCESS)
            with UnitOfWork(self.connection) as repositories:
                attachment = repositories.attachments.find_by_sha256(
                    "user-1",
                    hashlib.sha256(SAMPLE_GPX).hexdigest(),
                )
            self.assertEqual(Path(attachment.raw_path).read_bytes(), SAMPLE_GPX)
            self.assertEqual(attachment.metadata["storage_status"], "written")

    def test_duplicate_gpx_does_not_create_second_workout(self) -> None:
        first = self.dispatcher.dispatch(
            _gpx_event("event-1", "attachment-1", SAMPLE_GPX),
            DispatchContext(UnitOfWork(self.connection)),
        )
        second = self.dispatcher.dispatch(
            _gpx_event("event-2", "attachment-2", SAMPLE_GPX),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(first.status, WorkflowStatus.SUCCESS)
        self.assertEqual(second.status, WorkflowStatus.SUCCESS)
        self.assertEqual(second.messages[0].localized_text.key, TranslationKey.GPX_DUPLICATE)
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")
            attachments = repositories.attachments.find_by_sha256(
                "user-1",
                hashlib.sha256(SAMPLE_GPX).hexdigest(),
            )
        self.assertEqual(len(workouts), 1)
        self.assertIsNotNone(attachments)

    def test_duplicate_gpx_refreshes_derived_route_fields_without_renaming(self) -> None:
        sha256 = hashlib.sha256(COURSE_GPX).hexdigest()
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1")
            repositories.attachments.add(
                AttachmentRecord(
                    attachment_id="old-course-attachment",
                    owner_user_id="user-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    message_id="old-message",
                    filename="COURSE_476622335.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=len(COURSE_GPX),
                    sha256=sha256,
                    raw_path="raw/course.gpx",
                    created_at="2026-06-13T07:00:00Z",
                )
            )
            repositories.workouts.add(
                WorkoutRecord(
                    workout_id="workout-course",
                    owner_user_id="user-1",
                    source_attachment_id="old-course-attachment",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Custom course title",
                    kind="activity",
                    primary_kind="activity",
                    start_time_utc=None,
                    start_time_local=None,
                    local_date=None,
                    distance_km=31.628,
                    duration_s=None,
                    pace_s_per_km=None,
                    ascent_m=276,
                    avg_hr_bpm=None,
                    max_hr_bpm=None,
                    point_count=4,
                    created_at="2026-06-13T07:00:00Z",
                    metadata={"track_point_count": 3, "waypoint_count": 1},
                )
            )

        result = self.dispatcher.dispatch(
            _gpx_event("event-1", "new-course-attachment", COURSE_GPX),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.GPX_DUPLICATE_ROUTE)
        with UnitOfWork(self.connection) as repositories:
            workout = repositories.workouts.get_for_user("user-1", "workout-course")
            points = repositories.workout_streams.list_points("workout-course")
            features = repositories.workout_estimate_features.get("workout-course")

        self.assertEqual(workout.title, "Custom course title")
        self.assertEqual(workout.kind, "route_plan")
        self.assertEqual(workout.primary_kind, "route")
        self.assertLess(workout.distance_km or 0.0, 3.0)
        self.assertEqual(workout.point_count, 3)
        self.assertEqual(len(points), 3)
        self.assertIsNotNone(features)
        self.assertEqual(features.primary_kind, "route")
        self.assertLess(features.distance_km or 0.0, 3.0)

    def test_estimate_feature_backfill_rebuilds_missing_features(self) -> None:
        self.dispatcher.dispatch(
            _gpx_event("event-1", "attachment-1", SAMPLE_GPX),
            DispatchContext(UnitOfWork(self.connection)),
        )
        with UnitOfWork(self.connection) as repositories:
            workout = repositories.workouts.list_for_user("user-1")[0]
            repositories.workout_estimate_features.connection.execute(
                "DELETE FROM workout_estimate_features WHERE workout_id = ?",
                (workout.workout_id,),
            )

        with UnitOfWork(self.connection) as repositories:
            count = backfill_workout_estimate_features(repositories, owner_user_id="user-1", updated_at="2026-06-13T08:00:00Z")
            features = repositories.workout_estimate_features.get(workout.workout_id)

        self.assertEqual(count, 1)
        self.assertIsNotNone(features)
        self.assertEqual(features.updated_at, "2026-06-13T08:00:00Z")
        self.assertGreater(features.distance_km or 0.0, 0.0)
        self.assertIn("location", features.metadata)

    def test_duplicate_attachment_without_workout_creates_missing_workout(self) -> None:
        sha256 = hashlib.sha256(SAMPLE_GPX).hexdigest()
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1")
            repositories.attachments.add(
                AttachmentRecord(
                    attachment_id="orphan-attachment",
                    owner_user_id="user-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    message_id="old-message",
                    filename="old-run.gpx",
                    content_type="application/gpx+xml",
                    size_bytes=len(SAMPLE_GPX),
                    sha256=sha256,
                    raw_path="raw/orphan.gpx",
                    created_at="2026-06-13T07:00:00Z",
                )
            )

        result = self.dispatcher.dispatch(
            _gpx_event("event-1", "new-attachment", SAMPLE_GPX),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.GPX_ACCEPTED)
        self.assertEqual(result.messages[0].localized_text.params["filename"], "morning-run.gpx")
        with UnitOfWork(self.connection) as repositories:
            workouts = repositories.workouts.list_for_user("user-1")

        self.assertEqual(len(workouts), 1)
        self.assertEqual(workouts[0].source_attachment_id, "orphan-attachment")
        self.assertEqual(workouts[0].title, "Morning Run")

    def test_invalid_gpx_attachment_returns_user_error(self) -> None:
        result = self.dispatcher.dispatch(
            _gpx_event("event-1", "attachment-1", b"<gpx><trk></trk></gpx>"),
            DispatchContext(UnitOfWork(self.connection)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "invalid_gpx")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.GPX_REJECTED)
        self.assertEqual(result.messages[0].localized_text.params["filename"], "morning-run.gpx")

    def test_route_event_marks_gpx_attachment_as_ingest(self) -> None:
        from app.dispatcher import route_event

        route = route_event(_gpx_event("event-1", "attachment-1", SAMPLE_GPX))

        self.assertEqual(route.target, WorkflowTarget.GPX_INGEST)
        self.assertEqual(route.slots["attachment_ids"], ["attachment-1"])

    def test_unsupported_attachment_returns_user_error_without_llm(self) -> None:
        client = FakeLLMClient({})
        result = self.dispatcher.dispatch(
            _unsupported_attachment_event("event-1", "attachment-1"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "unsupported_attachment")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT)
        self.assertEqual(client.requests, [])

    def test_route_event_marks_unsupported_attachment_as_deterministic_ingest_error(self) -> None:
        from app.dispatcher import route_event

        route = route_event(_unsupported_attachment_event("event-1", "attachment-1"))

        self.assertEqual(route.target, WorkflowTarget.GPX_INGEST)
        self.assertEqual(route.slots["attachment_ids"], ["attachment-1"])
        self.assertTrue(route.slots["unsupported_attachment"])


def _gpx_event(
    event_id: str,
    attachment_id: str,
    content: bytes,
    *,
    text: str = "tallenna treeni",
    kind: EventKind = EventKind.MENTION,
    source: EventSource = EventSource.DISCORD_MESSAGE,
    extra_attachments: tuple[AttachmentRef, ...] = (),
    metadata: dict[str, object] | None = None,
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        source=source,
        kind=kind,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text=text,
        attachments=(
            AttachmentRef(
                attachment_id=attachment_id,
                filename="morning-run.gpx",
                content_type="application/gpx+xml",
                size_bytes=len(content),
                metadata={"content": content},
            ),
            *extra_attachments,
        ),
        created_at=datetime(2026, 6, 13, 7, 0, tzinfo=timezone.utc),
        metadata=metadata or {},
    )


def _unsupported_attachment_event(event_id: str, attachment_id: str) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text="katso tämä kuva",
        attachments=(
            AttachmentRef(
                attachment_id=attachment_id,
                filename="photo.png",
                content_type="image/png",
                size_bytes=123,
            ),
        ),
        created_at=datetime(2026, 6, 13, 7, 0, tzinfo=timezone.utc),
    )


def _gpx_with_elevations(elevations: tuple[float, ...]) -> bytes:
    points = "\n".join(
        (
            f'      <trkpt lat="{60.0 + index * 0.001:.6f}" lon="24.0">'
            f"<ele>{elevation}</ele><time>2026-06-13T06:{index:02d}:00Z</time></trkpt>"
        )
        for index, elevation in enumerate(elevations)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="aimo-test" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>Noise Test</name></metadata>
  <trk><trkseg>
{points}
  </trkseg></trk>
</gpx>
""".encode("utf-8")


if __name__ == "__main__":
    unittest.main()
