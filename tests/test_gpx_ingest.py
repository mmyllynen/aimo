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
from llm.gateway import FakeLLMClient, LLMGateway
from storage.repositories import AttachmentRecord
from storage.unit_of_work import UnitOfWork, open_database
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

        self.assertEqual(len(workouts), 1)
        self.assertEqual(active.workout_id, workouts[0].workout_id)
        self.assertEqual(len(points), 3)
        self.assertIn("heart_rate", {stream.stream_key for stream in streams})

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
    extra_attachments: tuple[AttachmentRef, ...] = (),
) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text="tallenna treeni",
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
