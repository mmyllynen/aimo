from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.dispatcher import DispatchContext, Dispatcher, route_event
from core.config import MapsConfig, RenderersConfig
from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource
from core.i18n import SupportedLanguage, TranslationKey
from core.routing import WorkflowTarget
from core.workflows import OutgoingKind, WorkflowStatus
from llm.gateway import FakeLLMClient, LLMGateway, LLMOperation
from llm.operations import VisualizationIntent
from storage.repositories import AttachmentRecord, HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from storage.unit_of_work import UnitOfWork, open_database
import visualization.service as visualization_service
from visualization.render import DEFAULT_RENDER_HEIGHT, DEFAULT_RENDER_WIDTH, _decode_png_rgb, _png
from visualization.tiles import TileFetchResult, TileImage
from workflows.visualization import _apply_visualization_modifiers, _period_title, _visualization_modifiers, _visualization_negative_modifiers
from workout.periods import PeriodBounds


class VisualizationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = open_database(apply_schema=True)
        self.dispatcher = Dispatcher()

    def tearDown(self) -> None:
        self.connection.close()

    def test_period_titles_are_localized(self) -> None:
        self.assertEqual(
            _period_title(
                _visualization_intent(("route",), workout_selector={"type": "all_workouts"}),
                PeriodBounds(label="all_workouts"),
                language=SupportedLanguage.FI,
            ),
            "Kaikki treenit",
        )
        self.assertEqual(
            _period_title(
                _visualization_intent(("route",), workout_selector={"type": "all_workouts"}),
                PeriodBounds(label="all_workouts"),
                language=SupportedLanguage.EN,
            ),
            "All workouts",
        )

    def test_visualization_modifiers_add_metrics_without_replacing_free_text_intent(self) -> None:
        intent = _visualization_intent(("heart_rate_bpm",))

        updated = _apply_visualization_modifiers(intent, "piirrä sykekäyrä +elevation +ELEVATION +portrait")

        self.assertEqual(_visualization_modifiers("piirrä +HR ja +elevation"), ("hr", "elevation"))
        self.assertEqual(_visualization_modifiers("piirrä #HR ja #elevation"), ())
        self.assertEqual(updated.y_metrics, ("heart_rate_bpm", "elevation_m"))
        self.assertEqual(updated.x_metric, intent.x_metric)
        self.assertEqual(updated.chart_kind, intent.chart_kind)
        self.assertEqual((updated.render_width, updated.render_height), (1080, 1920))

    def test_visualization_negative_modifiers_can_hide_waypoints(self) -> None:
        intent = _visualization_intent(("route",), x_metric="longitude", chart_kind="map")

        updated = _apply_visualization_modifiers(intent, "näytä reitti kartalla -waypoints -reittimerkit -elevation -korkeus +hr")

        self.assertEqual(_visualization_negative_modifiers("näytä reitti -waypoints ja -reittimerkit -elevation -korkeus"), ("waypoints", "reittimerkit", "elevation", "korkeus"))
        self.assertEqual(_visualization_modifiers("näytä reitti -waypoints +hr"), ("hr",))
        self.assertEqual(updated.social_style["waypoints"], False)
        self.assertEqual(updated.social_style["elevation_overlay"], False)
        self.assertEqual(updated.route_color_metric, "heart_rate_bpm")

    def test_visualization_aspect_modifiers_use_first_known_size(self) -> None:
        intent = _visualization_intent(("heart_rate_bpm",))

        portrait = _apply_visualization_modifiers(intent, "piirrä sykekäyrä +portrait +square")
        square = _apply_visualization_modifiers(intent, "piirrä sykekäyrä +square +portrait")

        self.assertEqual((portrait.render_width, portrait.render_height), (1080, 1920))
        self.assertEqual((square.render_width, square.render_height), (1080, 1080))

    def test_visualization_aspect_modifiers_support_landscape(self) -> None:
        intent = _visualization_intent(("heart_rate_bpm",))

        updated = _apply_visualization_modifiers(intent, "piirrä somekuva +landscape")

        self.assertEqual((updated.render_width, updated.render_height), (1920, 1080))

    def test_visualization_modifier_sets_route_color_metric_for_map(self) -> None:
        intent = _visualization_intent(("route",), x_metric="longitude", chart_kind="map")

        updated = _apply_visualization_modifiers(intent, "piirrä viimeisin treeni kartalle +hr +pace")

        self.assertEqual(updated.y_metrics, ("route", "heart_rate_bpm"))
        self.assertEqual(updated.route_color_metric, "heart_rate_bpm")
        self.assertEqual(updated.route_color_ignored_metrics, ("pace_s_per_km",))

    def test_visualization_modifier_maps_social_stat_aliases(self) -> None:
        intent = _visualization_intent(("route",), x_metric="longitude", chart_kind="map", output_mode="social_image")

        updated = _apply_visualization_modifiers(intent, "piirrä somekuva +kesto +duration +hr +nousumetrit +pace +date +maxhr")

        self.assertEqual(updated.y_metrics, ("route", "duration_s", "avg_hr_bpm", "ascent_m", "pace_s_per_km", "local_date", "max_hr_bpm"))
        self.assertEqual(updated.output_mode, "social_image")

    def test_visualization_modifier_can_force_social_output_mode(self) -> None:
        intent = _visualization_intent(("heart_rate_bpm",))

        updated = _apply_visualization_modifiers(intent, "piirrä viimeisin treeni +somekuva +date")

        self.assertEqual(updated.output_mode, "social_image")
        self.assertEqual(updated.chart_kind, "map")
        self.assertEqual(updated.y_metrics, ("heart_rate_bpm", "route", "local_date"))

    def test_latest_workout_visualization_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("heart_rate_bpm",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(result.messages[0].content), 1000)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.VISUALIZATION_CREATED)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_bpm",))

    def test_route_map_backfills_waypoints_from_raw_gpx_for_old_uploads(self) -> None:
        gpx = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="aimo-test" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata><name>Route</name></metadata>
  <wpt lat="60.175" lon="24.945"><name>Info</name><cmt>Aid station</cmt><type>INFO</type></wpt>
  <trk><trkseg>
    <trkpt lat="60.170" lon="24.940" />
    <trkpt lat="60.180" lon="24.950" />
  </trkseg></trk>
</gpx>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "route.gpx"
            raw_path.write_bytes(gpx)
            with UnitOfWork(self.connection) as repositories:
                repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
                repositories.attachments.add(
                    AttachmentRecord(
                        attachment_id="attachment-1",
                        owner_user_id="user-1",
                        guild_id="guild-1",
                        channel_id="channel-1",
                        message_id="message-1",
                        filename="route.gpx",
                        content_type="application/gpx+xml",
                        size_bytes=len(gpx),
                        sha256="sha",
                        raw_path=str(raw_path),
                        created_at="2026-06-18T05:00:00Z",
                    )
                )
                workout = WorkoutRecord(
                    workout_id="route-1",
                    owner_user_id="user-1",
                    source_attachment_id="attachment-1",
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Route",
                    kind="route_plan",
                    primary_kind="route",
                    start_time_utc=None,
                    start_time_local=None,
                    local_date=None,
                    distance_km=1.0,
                    duration_s=None,
                    pace_s_per_km=None,
                    ascent_m=None,
                    avg_hr_bpm=None,
                    max_hr_bpm=None,
                    point_count=2,
                    created_at="2026-06-18T05:00:00Z",
                    metadata={"track_point_count": 2, "route_point_count": 0, "waypoint_count": 1},
                )
                repositories.workouts.add(workout)
                repositories.workout_streams.replace_for_workout(
                    workout.workout_id,
                    points=(
                        WorkoutPointRecord(workout_id="route-1", point_index=0, latitude=60.170, longitude=24.940),
                        WorkoutPointRecord(workout_id="route-1", point_index=1, latitude=60.180, longitude=24.950),
                    ),
                    streams=(),
                )
                repositories.active_workouts.set(user_id="user-1", workout_id="route-1", updated_at="2026-06-18T05:00:00Z")
            client = _visualization_client(_intent(("route",), x_metric="route", chart_kind="map", workout_selector={"type": "active"}))

            result = self.dispatcher.dispatch(
                _mention("event-route-waypoints", "näytä reitti kartalla"),
                DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client), renderers_config=RenderersConfig(default="pillow")),
            )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["waypoint_count"], 1)
        self.assertEqual(result.messages[0].metadata["waypoints_rendered"], 1)
        self.assertEqual(result.messages[0].metadata["waypoint_status"], "rendered")
        with UnitOfWork(self.connection) as repositories:
            refreshed = repositories.workouts.get_for_user("user-1", "route-1")
        self.assertEqual(refreshed.metadata["waypoints"][0]["name"], "Info")
        self.assertEqual(refreshed.metadata["waypoints"][0]["comment"], "Aid station")
        self.assertEqual(refreshed.metadata["waypoints"][0]["type"], "INFO")

    def test_latest_workout_social_image_defaults_to_square_map_background(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map", output_mode="social_image"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä somekuva viimeisestä treenistä"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client), renderers_config=RenderersConfig(default="pillow")),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.messages[0].filename, "workout-1-social-image.png")
        self.assertEqual(result.messages[0].metadata["chart_type"], "social_image")
        self.assertEqual(result.messages[0].metadata["social_background"], "map")
        self.assertEqual((result.messages[0].metadata["render_width"], result.messages[0].metadata["render_height"]), (1080, 1080))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("distance_km", "duration_s", "avg_hr_bpm"))

    def test_latest_workout_social_image_uses_attached_image_background_and_requested_stats(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(
            _intent(
                ("route", "distance_km", "duration_s", "avg_hr_bpm", "ascent_m"),
                x_metric="longitude",
                chart_kind="map",
                output_mode="social_image",
            )
        )

        result = self.dispatcher.dispatch(
            _mention(
                "event-1",
                "piirrä somekuva viimeisestä treenistä +distance +duration +hr +ascent +portrait",
                attachments=(
                    AttachmentRef(
                        attachment_id="photo-1",
                        filename="photo.png",
                        content_type="image/png",
                        metadata={"content": _png(140, 90, bytearray((40, 80, 120) * 140 * 90))},
                    ),
                ),
            ),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client), renderers_config=RenderersConfig(default="pillow")),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["social_background"], "attachment")
        self.assertEqual(result.messages[0].metadata["social_layout_version"], "2")
        self.assertEqual((result.messages[0].metadata["render_width"], result.messages[0].metadata["render_height"]), (1080, 1920))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("distance_km", "duration_s", "avg_hr_bpm", "ascent_m"))

    def test_latest_workout_social_image_invalid_attachment_falls_back_to_map(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map", output_mode="social_image"))

        result = self.dispatcher.dispatch(
            _mention(
                "event-1",
                "piirrä somekuva viimeisestä treenistä",
                attachments=(
                    AttachmentRef(
                        attachment_id="photo-1",
                        filename="photo.png",
                        content_type="image/png",
                        metadata={"content": b"not an image"},
                    ),
                ),
            ),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client), renderers_config=RenderersConfig(default="pillow")),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["social_background"], "map")
        self.assertEqual(result.messages[0].metadata["social_background_status"], "invalid_image_fallback_to_map")

    def test_latest_workout_social_image_without_route_returns_specific_error(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=False)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map", output_mode="social_image"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä somekuva viimeisestä treenistä"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client), renderers_config=RenderersConfig(default="pillow")),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_SOCIAL_IMAGE_REQUIRES_ROUTE)

    def test_latest_workout_visualization_writes_artifact_when_root_is_configured(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = _visualization_client(_intent(("heart_rate_bpm",)))
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.dispatcher.dispatch(
                _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
                DispatchContext(UnitOfWork(self.connection), artifact_path=Path(tmpdir), llm_gateway=LLMGateway(client)),
            )

            self.assertEqual(result.status, WorkflowStatus.SUCCESS)
            with UnitOfWork(self.connection) as repositories:
                artifacts = repositories.rendered_artifacts.list_for_user("user-1")
            self.assertEqual(len(artifacts), 1)
            self.assertEqual(Path(artifacts[0].storage_path).read_bytes(), result.messages[0].content)
            self.assertEqual(artifacts[0].metadata["storage_status"], "written")

    def test_visualization_artifact_stores_compact_revision_context(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = _visualization_client(_intent(("heart_rate_bpm",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            artifact = repositories.rendered_artifacts.latest_visualization_for_user("user-1", channel_id="channel-1")
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.metadata["channel_id"], "channel-1")
        self.assertEqual(artifact.metadata["workout_id"], "workout-1")
        self.assertEqual(artifact.metadata["intent"]["x_metric"], "elapsed_s")
        self.assertEqual(artifact.metadata["intent"]["y_metrics"], ["heart_rate_bpm"])
        self.assertNotIn("workout_points", artifact.metadata)
        self.assertNotIn("raw_points", artifact.metadata)

    def test_latest_workout_visualization_scales_secondary_series(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = _visualization_client(
            _intent(
                ("heart_rate_bpm", "pace_s_per_km", "elevation_m"),
                transforms=("normalize_to_primary_range",),
                layout_mode="single_axis",
            )
        )

        result = self.dispatcher.dispatch(
            _mention(
                "event-1",
                "piirrä viimeisimmästä treenistä syke ajan funktiona, piirrä samaan kuvaajaan myös vauhti ja maaston korkeuskäyrät skaalattuna samalle alueelle",
            ),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(
            result.messages[0].metadata["rendered_metrics"],
            ("heart_rate_bpm", "pace_s_per_km", "elevation_m"),
        )
        self.assertEqual(result.messages[0].metadata["scaled_metrics"], ("pace_s_per_km", "elevation_m"))

    def test_latest_workout_hr_zone_distribution_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=True)
        client = _visualization_client(_intent(("heart_rate_zone_seconds",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin sykealuejakauma"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.messages[0].filename, "workout-1-hr-zone-distribution.png")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))

    def test_latest_workout_hr_zone_distribution_percentage_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=True)
        client = _visualization_client(_intent(("heart_rate_zone_seconds",), transforms=("as_percentage_of_total",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin sykealuejakauma prosentuaalisesti"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))

    def test_latest_workout_hr_zone_distribution_pie_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=True)
        client = _visualization_client(
            _intent(("heart_rate_zone_seconds",), transforms=("as_percentage_of_total",), chart_kind="pie")
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "tee viimeisimmän treenin sykealuejakaumasta piirakkagraafi prosentteina"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))

    def test_current_month_hr_zone_pie_uses_period_workout_set(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="First run",
            with_heart_rate=True,
            with_zones=True,
            local_date="2026-06-01",
            start_time_local="2026-06-01T10:00:00+03:00",
            created_at="2026-06-01T10:30:00Z",
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Second run",
            with_heart_rate=True,
            with_zones=False,
            local_date="2026-06-13",
            start_time_local="2026-06-13T10:00:00+03:00",
            created_at="2026-06-13T10:30:00Z",
        )
        client = _visualization_client(
            _intent(
                ("heart_rate_zone_seconds",),
                transforms=("as_percentage_of_total",),
                chart_kind="pie",
                workout_selector={"type": "current_month", "value": "", "count": None, "limit": None},
                date_range={"start": "", "end": ""},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "näytä kuluvan kuun treenien sykealueet piirakkagraafina"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].metadata["scope_type"], "workout_set")
        self.assertEqual(result.messages[0].metadata["workout_ids"], ("workout-1", "workout-2"))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))
        with UnitOfWork(self.connection) as repositories:
            artifact = repositories.rendered_artifacts.latest_visualization_for_user("user-1", channel_id="channel-1")
        self.assertEqual(artifact.metadata["scope_type"], "workout_set")
        self.assertEqual(artifact.metadata["workout_ids"], ["workout-1", "workout-2"])
        self.assertEqual(artifact.metadata["period_start_date"], "2026-06-01")
        self.assertEqual(artifact.metadata["period_end_date"], "2026-06-17")
        self.assertEqual(artifact.metadata["workout_id"], "period-event-1")

    def test_date_selector_with_date_range_uses_period_workout_set(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="First run",
            with_heart_rate=True,
            with_zones=True,
            local_date="2026-06-01",
            start_time_local="2026-06-01T10:00:00+03:00",
            created_at="2026-06-01T10:30:00Z",
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Second run",
            with_heart_rate=True,
            with_zones=False,
            local_date="2026-06-13",
            start_time_local="2026-06-13T10:00:00+03:00",
            created_at="2026-06-13T10:30:00Z",
        )
        client = _visualization_client(
            _intent(
                ("heart_rate_zone_seconds",),
                transforms=("as_percentage_of_total",),
                chart_kind="pie",
                workout_selector={"type": "date", "value": "", "count": None, "limit": None},
                date_range={"start": "2026-06-01", "end": "2026-06-30"},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "näytä kesäkuun treenien sykealueet piirakkagraafina"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["scope_type"], "workout_set")
        self.assertEqual(result.messages[0].metadata["workout_ids"], ("workout-1", "workout-2"))

    def test_current_month_ascent_bar_uses_generic_period_dataset(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="First run",
            with_heart_rate=True,
            local_date="2026-06-01",
            start_time_local="2026-06-01T10:00:00+03:00",
            created_at="2026-06-01T10:30:00Z",
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Second run",
            with_heart_rate=True,
            local_date="2026-06-13",
            start_time_local="2026-06-13T10:00:00+03:00",
            created_at="2026-06-13T10:30:00Z",
        )
        client = _visualization_client(
            _intent(
                ("ascent_m",),
                chart_kind="bar",
                workout_selector={"type": "current_month", "value": "", "count": None, "limit": None},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä kuluvan kuun treenien nousumetrit pylväinä"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["scope_type"], "workout_set")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("ascent_m",))

    def test_latest_workout_hr_zone_distribution_requires_configured_zones(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=False)
        client = _visualization_client(_intent(("heart_rate_zone_seconds",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin sykealuejakauma"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "missing_metric")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.HR_ZONES_EMPTY)

    def test_latest_workout_route_map_returns_png_file(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin reitti kartalle"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].filename, "workout-1-route-map.png")
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("route",))
        self.assertEqual(_decode_png_rgb(result.messages[0].content)[:2], (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT))

    def test_ambiguous_route_map_request_uses_active_route_context(self) -> None:
        self._seed_latest_activity_and_active_route()
        client = _visualization_client(
            _intent(
                ("route",),
                x_metric="longitude",
                chart_kind="map",
                workout_selector={"type": "", "value": ""},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "näytä reitti kartalla"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["workout_id"], "route-1")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("route",))
        request = next(request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT)
        active = request.user_payload["compact_routing_context"]["active_workout"]
        self.assertEqual(active["workout_id"], "route-1")
        self.assertEqual(active["primary_kind"], "route")
        self.assertTrue(active["has_route_points"])

    def test_explicit_latest_route_map_still_uses_latest_by_start_time(self) -> None:
        self._seed_latest_activity_and_active_route()
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map", workout_selector={"type": "latest"}))

        result = self.dispatcher.dispatch(
            _mention("event-1", "näytä viimeisin reitti kartalla"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["workout_id"], "activity-1")

    def test_route_map_modifier_colors_single_workout_route_by_heart_rate(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisin treeni kartalle +hr +portrait"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("route", "heart_rate_bpm"))
        self.assertEqual(result.messages[0].metadata["route_color_metric"], "heart_rate_bpm")
        self.assertEqual(result.messages[0].metadata["route_color_status"], "ok")
        self.assertEqual(result.messages[0].metadata["render_width"], 1080)
        self.assertEqual(result.messages[0].metadata["render_height"], 1920)
        self.assertEqual(_decode_png_rgb(result.messages[0].content)[:2], (1080, 1920))

    def test_route_map_multiple_color_modifiers_warn_and_use_first_metric(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisin treeni kartalle +hr +pace"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(len(result.messages), 2)
        self.assertEqual(result.messages[0].metadata["route_color_metric"], "heart_rate_bpm")
        self.assertEqual(result.messages[0].metadata["route_color_ignored_metrics"], ("pace_s_per_km",))
        self.assertEqual(result.messages[1].localized_text.key, TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED)
        self.assertEqual(result.messages[1].localized_text.params["metric"], "syke")

    def test_route_map_uses_tile_background_metadata_when_cache_root_is_configured(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))
        original_fetch_tiles = visualization_service.fetch_tiles

        def fake_fetch_tiles(coords, config):
            del config
            content = _png(256, 256, bytearray((171, 205, 239) * 256 * 256))
            return TileFetchResult(tiles=tuple(TileImage(coord=coord, content=content, source="cache") for coord in coords))

        visualization_service.fetch_tiles = fake_fetch_tiles
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = self.dispatcher.dispatch(
                    _mention("event-1", "piirrä viimeisimmän treenin reitti kartalle"),
                    DispatchContext(
                        UnitOfWork(self.connection),
                        artifact_path=Path(tmpdir) / "artifacts",
                        llm_gateway=LLMGateway(client),
                    ),
                )
        finally:
            visualization_service.fetch_tiles = original_fetch_tiles

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["map_background"], "osm")
        self.assertEqual(result.messages[0].metadata["tile_status"], "ok")
        self.assertGreater(result.messages[0].metadata["tile_count"], 0)
        with UnitOfWork(self.connection) as repositories:
            artifact = repositories.rendered_artifacts.latest_visualization_for_user("user-1", channel_id="channel-1")
        self.assertEqual(artifact.metadata["map_background"], "osm")
        self.assertEqual(artifact.metadata["tile_status"], "ok")

    def test_route_map_prefers_configured_maptiler_tile_provider(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=True)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))
        original_fetch_tiles = visualization_service.fetch_tiles

        def fake_fetch_tiles(coords, config):
            del config
            content = _png(512, 512, bytearray((171, 205, 239) * 512 * 512))
            return TileFetchResult(tiles=tuple(TileImage(coord=coord, content=content, source="network") for coord in coords))

        visualization_service.fetch_tiles = fake_fetch_tiles
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                result = self.dispatcher.dispatch(
                    _mention("event-1", "piirrä viimeisimmän treenin reitti kartalle"),
                    DispatchContext(
                        UnitOfWork(self.connection),
                        artifact_path=Path(tmpdir) / "artifacts",
                        llm_gateway=LLMGateway(client),
                        maps_config=MapsConfig(provider="maptiler", maptiler_api_key="test-key"),
                        renderers_config=RenderersConfig(route="pillow"),
                    ),
                )
        finally:
            visualization_service.fetch_tiles = original_fetch_tiles

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["map_background"], "maptiler_tiles")
        self.assertEqual(result.messages[0].metadata["tile_provider"], "maptiler")
        self.assertEqual(result.messages[0].metadata["tile_size"], 512)
        self.assertEqual(result.messages[0].metadata["route_overlay"], "aimo")
        self.assertEqual(result.messages[0].metadata["renderer"], "pillow")
        self.assertEqual(_decode_png_rgb(result.messages[0].content)[:2], (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT))

    def test_current_month_route_map_uses_period_workout_set(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="First run",
            with_heart_rate=True,
            with_location=True,
            local_date="2026-06-01",
            start_time_local="2026-06-01T10:00:00+03:00",
            created_at="2026-06-01T10:30:00Z",
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Second run",
            with_heart_rate=True,
            with_location=True,
            local_date="2026-06-13",
            start_time_local="2026-06-13T10:00:00+03:00",
            created_at="2026-06-13T10:30:00Z",
        )
        client = _visualization_client(
            _intent(
                ("route",),
                x_metric="longitude",
                chart_kind="map",
                workout_selector={"type": "current_month", "value": "", "count": None, "limit": None},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä kuluvan kuun treenien reitit kartalle"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["scope_type"], "workout_set")
        self.assertEqual(result.messages[0].metadata["workout_ids"], ("workout-1", "workout-2"))
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("route",))
        self.assertTrue(result.messages[0].content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_current_month_route_map_modifier_colors_multiple_routes_by_heart_rate(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="First run",
            with_heart_rate=True,
            with_location=True,
            local_date="2026-06-01",
            start_time_local="2026-06-01T10:00:00+03:00",
            created_at="2026-06-01T10:30:00Z",
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Second run",
            with_heart_rate=True,
            with_location=True,
            local_date="2026-06-13",
            start_time_local="2026-06-13T10:00:00+03:00",
            created_at="2026-06-13T10:30:00Z",
        )
        client = _visualization_client(
            _intent(
                ("route",),
                x_metric="longitude",
                chart_kind="map",
                workout_selector={"type": "current_month", "value": "", "count": None, "limit": None},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä kuluvan kuun treenien reitit kartalle +hr"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["scope_type"], "workout_set")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("route", "heart_rate_bpm"))
        self.assertEqual(result.messages[0].metadata["route_color_metric"], "heart_rate_bpm")
        self.assertEqual(result.messages[0].metadata["route_color_status"], "ok")

    def test_latest_workout_route_map_requires_gps_points(self) -> None:
        self._seed_workout(with_heart_rate=True, with_location=False)
        client = _visualization_client(_intent(("route",), x_metric="longitude", chart_kind="map"))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmän treenin reitti kartalle"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "missing_metric")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_MISSING_METRIC)
        self.assertEqual(result.messages[0].localized_text.params["metric"], "route")

    def test_latest_workout_missing_primary_metric_returns_specific_error_without_clarification(self) -> None:
        self._seed_workout(with_heart_rate=False)
        client = _visualization_client(_intent(("heart_rate_bpm",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "missing_metric")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_MISSING_METRIC)
        self.assertEqual(result.messages[0].localized_text.params["metric"], "heart_rate_bpm")

    def test_visualization_intent_llm_input_does_not_include_workout_points(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = _visualization_client(_intent(("heart_rate_bpm",)))

        result = self.dispatcher.dispatch(
            _mention("event-1", "draw latest heart rate chart"),
            DispatchContext(
                UnitOfWork(self.connection),
                language=SupportedLanguage.EN,
                llm_gateway=LLMGateway(client),
            ),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        visualization_request = next(
            request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT
        )
        self.assertNotIn("workout_points", visualization_request.user_payload)
        self.assertNotIn("raw_points", visualization_request.user_payload)

    def test_visualization_refinement_sends_previous_context_to_llm_without_raw_points(self) -> None:
        self._seed_workout(with_heart_rate=True)
        first_client = _visualization_client(_intent(("heart_rate_bpm",)))
        first_result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä syke ajan funktiona"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(first_client)),
        )
        self.assertEqual(first_result.status, WorkflowStatus.SUCCESS)
        client = _visualization_client(_intent(("heart_rate_bpm", "pace_s_per_km")))

        result = self.dispatcher.dispatch(
            _mention("event-2", "lisää edelliseen kuvaajaan vauhti"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        visualization_request = next(
            request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT
        )
        previous = visualization_request.user_payload["previous_visualization"]
        self.assertEqual(previous["workout_id"], "workout-1")
        self.assertEqual(previous["channel_id"], "channel-1")
        self.assertEqual(previous["intent"]["y_metrics"], ["heart_rate_bpm"])
        self.assertNotIn("workout_points", visualization_request.user_payload)
        self.assertNotIn("raw_points", visualization_request.user_payload)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_bpm", "pace_s_per_km"))

    def test_same_chart_pie_refinement_uses_llm_previous_context(self) -> None:
        self._seed_workout(with_heart_rate=True, with_zones=True)
        first_client = _visualization_client(_intent(("heart_rate_zone_seconds",)))
        first_result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä viimeisimmästä treenistä sykealuejakauma"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(first_client)),
        )
        self.assertEqual(first_result.status, WorkflowStatus.SUCCESS)
        client = _visualization_client(
            _intent(("heart_rate_zone_seconds",), transforms=("as_percentage_of_total",), chart_kind="pie")
        )

        result = self.dispatcher.dispatch(
            _mention("event-2", "piirrä sama piirakkakuviona jakauma prosentuaalisesti"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].content_type, "image/png")
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_zone_seconds",))
        visualization_request = next(
            request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT
        )
        previous = visualization_request.user_payload["previous_visualization"]
        self.assertEqual(previous["intent"]["y_metrics"], ["heart_rate_zone_seconds"])
        self.assertEqual(visualization_request.user_payload["compact_routing_context"]["has_previous_visualization"], True)

    def test_invalid_render_plan_is_revised_once_with_safe_context(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = FakeLLMClient(
            {
                LLMOperation.INTENT_CLASSIFICATION: _classification(),
                LLMOperation.VISUALIZATION_INTENT: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["invented_metric"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                    "chart_kind": "auto",
                    "output_mode": "chart",
                    "context_update": {"set_current_workout": False},
                },
                LLMOperation.VISUALIZATION_INTENT_REVISION: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["heart_rate_bpm"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                    "chart_kind": "auto",
                    "output_mode": "chart",
                    "context_update": {"set_current_workout": False},
                }
            }
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "draw latest heart rate chart"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("heart_rate_bpm",))
        revision_request = next(
            request for request in client.requests if request.operation == LLMOperation.VISUALIZATION_INTENT_REVISION
        )
        self.assertEqual(revision_request.user_payload["failed_intent"]["y_metrics"], ["invented_metric"])
        self.assertEqual(revision_request.user_payload["validation_errors"][0]["code"], "unsupported_column")
        self.assertIn("heart_rate_bpm", revision_request.user_payload["validation_errors"][0]["allowed_values"])
        self.assertIn("chart_kinds", revision_request.user_payload["allowed_primitives"])
        dataset_manifest = revision_request.user_payload["dataset_manifest"]
        self.assertIn("datasets", dataset_manifest)
        self.assertNotIn("rows", str(dataset_manifest))
        self.assertNotIn("workout_points", revision_request.user_payload)
        self.assertNotIn("raw_points", revision_request.user_payload)

    def test_invalid_render_plan_after_revision_returns_user_error(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = FakeLLMClient(
            {
                LLMOperation.INTENT_CLASSIFICATION: _classification(),
                LLMOperation.VISUALIZATION_INTENT: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["invented_metric"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                    "chart_kind": "auto",
                    "output_mode": "chart",
                    "context_update": {"set_current_workout": False},
                },
                LLMOperation.VISUALIZATION_INTENT_REVISION: {
                    "workout_selector": {"type": "latest"},
                    "x_metric": "elapsed_s",
                    "requested_metrics": ["invented_metric"],
                    "transform_hints": [],
                    "date_range": {},
                    "comparison_mode": "",
                    "layout_mode": "auto",
                    "chart_kind": "auto",
                    "output_mode": "chart",
                    "context_update": {"set_current_workout": False},
                },
            }
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "draw latest heart rate chart"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.USER_ERROR)
        self.assertEqual(result.error.category.value, "visualization_plan_invalid")
        self.assertEqual(result.messages[0].localized_text.key, TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID)

    def test_route_event_uses_llm_for_chart_language(self) -> None:
        client = FakeLLMClient({LLMOperation.INTENT_CLASSIFICATION: _classification()})

        route = route_event(_mention("event-1", "piirrä kuvaaja viimeisimmästä treenistä"), llm_gateway=LLMGateway(client))

        self.assertEqual(route.target, WorkflowTarget.VISUALIZATION)

    def test_route_event_does_not_parse_chart_language_without_llm(self) -> None:
        route = route_event(_mention("event-1", "piirrä kuvaaja viimeisimmästä treenistä"))

        self.assertEqual(route.target, WorkflowTarget.CHAT)

    def test_comparison_visualization_uses_recent_owned_workouts(self) -> None:
        self._seed_workout(
            workout_id="workout-1",
            title="Older run",
            distance_km=5.0,
            created_at="2026-06-12T10:30:00Z",
            start_time_local="2026-06-12T10:00:00+03:00",
            local_date="2026-06-12",
            with_heart_rate=True,
        )
        self._seed_workout(
            workout_id="workout-2",
            title="Newer run",
            distance_km=7.0,
            created_at="2026-06-13T10:30:00Z",
            start_time_local="2026-06-13T10:00:00+03:00",
            local_date="2026-06-13",
            with_heart_rate=True,
        )
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-2", seen_at="2026-06-13T09:00:00Z")
            repositories.workouts.add(
                WorkoutRecord(
                    workout_id="other-user-workout",
                    owner_user_id="user-2",
                    source_attachment_id=None,
                    guild_id="guild-1",
                    channel_id="channel-1",
                    title="Other user run",
                    kind="activity",
                    primary_kind="activity",
                    start_time_utc="2026-06-14T07:00:00Z",
                    start_time_local="2026-06-14T10:00:00+03:00",
                    local_date="2026-06-14",
                    distance_km=99.0,
                    duration_s=600,
                    pace_s_per_km=600,
                    ascent_m=10,
                    avg_hr_bpm=130,
                    max_hr_bpm=140,
                    point_count=0,
                    created_at="2026-06-14T10:30:00Z",
                )
            )
        client = _visualization_client(
            _intent(
                ("distance_km",),
                comparison_mode="recent",
                workout_selector={"type": "latest", "count": 2, "limit": 2},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "vertaa kahta viimeisintä treeniä matkan perusteella"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        self.assertEqual(result.messages[0].kind, OutgoingKind.FILE)
        self.assertEqual(result.messages[0].metadata["rendered_metrics"], ("distance_km",))
        self.assertEqual(result.messages[0].metadata["workout_id"], "workout-2")

    def test_visualization_sets_current_workout_when_llm_requests_context_update(self) -> None:
        self._seed_workout(with_heart_rate=True)
        client = _visualization_client(
            _intent(
                ("heart_rate_bpm",),
                context_update={"set_current_workout": True},
            )
        )

        result = self.dispatcher.dispatch(
            _mention("event-1", "piirrä tästä treenistä syke"),
            DispatchContext(UnitOfWork(self.connection), llm_gateway=LLMGateway(client)),
        )

        self.assertEqual(result.status, WorkflowStatus.SUCCESS)
        with UnitOfWork(self.connection) as repositories:
            active = repositories.active_workouts.get("user-1")
        self.assertEqual(active.workout_id, "workout-1")

    def _seed_workout(
        self,
        *,
        with_heart_rate: bool,
        with_zones: bool = False,
        with_location: bool = False,
        workout_id: str = "workout-1",
        title: str = "Morning run",
        distance_km: float = 1.0,
        created_at: str = "2026-06-13T10:30:00Z",
        start_time_local: str = "2026-06-13T10:00:00+03:00",
        local_date: str = "2026-06-13",
    ) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            if with_zones:
                repositories.heart_rate_zones.replace_for_user(
                    "user-1",
                    (
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z1",
                            label="Easy",
                            upper_bpm=124,
                            sort_order=1,
                        ),
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z2",
                            label="Steady",
                            lower_bpm=125,
                            upper_bpm=134,
                            sort_order=2,
                        ),
                        HeartRateZoneRecord(
                            user_id="user-1",
                            zone_key="z3",
                            label="Hard",
                            lower_bpm=135,
                            sort_order=3,
                        ),
                    ),
                )
            workout = WorkoutRecord(
                workout_id=workout_id,
                owner_user_id="user-1",
                source_attachment_id=None,
                guild_id="guild-1",
                channel_id="channel-1",
                title=title,
                kind="activity",
                primary_kind="activity",
                start_time_utc=start_time_local,
                start_time_local=start_time_local,
                local_date=local_date,
                distance_km=distance_km,
                duration_s=600,
                pace_s_per_km=600,
                ascent_m=10,
                avg_hr_bpm=130 if with_heart_rate else None,
                max_hr_bpm=140 if with_heart_rate else None,
                point_count=3,
                created_at=created_at,
            )
            repositories.workouts.add(workout)
            repositories.workout_streams.replace_for_workout(
                workout.workout_id,
                points=(
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=0,
                        elapsed_s=0,
                        distance_km=0,
                        latitude=60.17 if with_location else None,
                        longitude=24.94 if with_location else None,
                        elevation_m=10,
                        heart_rate_bpm=120 if with_heart_rate else None,
                        pace_s_per_km=620,
                    ),
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=1,
                        elapsed_s=300,
                        distance_km=0.5,
                        latitude=60.171 if with_location else None,
                        longitude=24.945 if with_location else None,
                        elevation_m=15,
                        heart_rate_bpm=130 if with_heart_rate else None,
                        pace_s_per_km=600,
                    ),
                    WorkoutPointRecord(
                        workout_id=workout.workout_id,
                        point_index=2,
                        elapsed_s=600,
                        distance_km=1.0,
                        latitude=60.173 if with_location else None,
                        longitude=24.95 if with_location else None,
                        elevation_m=20,
                        heart_rate_bpm=140 if with_heart_rate else None,
                        pace_s_per_km=580,
                    ),
                ),
                streams=(),
            )

    def _seed_latest_activity_and_active_route(self) -> None:
        with UnitOfWork(self.connection) as repositories:
            repositories.users.touch(user_id="user-1", seen_at="2026-06-13T09:00:00Z")
            activity = WorkoutRecord(
                workout_id="activity-1",
                owner_user_id="user-1",
                source_attachment_id=None,
                guild_id="guild-1",
                channel_id="channel-1",
                title="Sipoo Running",
                kind="activity",
                primary_kind="activity",
                start_time_utc="2026-06-16T03:27:42Z",
                start_time_local="2026-06-16T03:27:42Z",
                local_date="2026-06-16",
                distance_km=5.4,
                duration_s=1800,
                pace_s_per_km=333,
                ascent_m=50,
                avg_hr_bpm=130,
                max_hr_bpm=150,
                point_count=3,
                created_at="2026-06-16T12:16:37Z",
            )
            route = WorkoutRecord(
                workout_id="route-1",
                owner_user_id="user-1",
                source_attachment_id=None,
                guild_id="guild-1",
                channel_id="channel-1",
                title="Juhannusreitti",
                kind="route_plan",
                primary_kind="route",
                start_time_utc=None,
                start_time_local=None,
                local_date=None,
                distance_km=23.9,
                duration_s=None,
                pace_s_per_km=None,
                ascent_m=276,
                avg_hr_bpm=None,
                max_hr_bpm=None,
                point_count=3,
                created_at="2026-06-18T04:29:34Z",
            )
            for workout in (activity, route):
                repositories.workouts.add(workout)
                repositories.workout_streams.replace_for_workout(
                    workout.workout_id,
                    points=(
                        WorkoutPointRecord(workout_id=workout.workout_id, point_index=0, latitude=60.17, longitude=24.94),
                        WorkoutPointRecord(workout_id=workout.workout_id, point_index=1, latitude=60.18, longitude=24.95),
                        WorkoutPointRecord(workout_id=workout.workout_id, point_index=2, latitude=60.19, longitude=24.96),
                    ),
                    streams=(),
                )
            repositories.active_workouts.set(
                user_id="user-1",
                workout_id=route.workout_id,
                updated_at="2026-06-18T04:29:34Z",
            )


def _mention(event_id: str, text: str, *, attachments: tuple[AttachmentRef, ...] = ()) -> CanonicalEvent:
    return CanonicalEvent(
        event_id=event_id,
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION,
        guild_id="guild-1",
        channel_id="channel-1",
        user_id="user-1",
        user_name="runner",
        text=text,
        attachments=attachments,
    )


def _classification() -> dict[str, object]:
    return {
        "workflow": "visualization",
        "confidence": "high",
        "slots": {},
        "clarification": "",
        "reason": "LLM classified the request as visualization.",
    }


def _intent(
    metrics: tuple[str, ...],
    *,
    x_metric: str = "elapsed_s",
    transforms: tuple[str, ...] = (),
    comparison_mode: str = "",
    layout_mode: str = "auto",
    chart_kind: str = "auto",
    workout_selector: dict[str, object] | None = None,
    context_update: dict[str, object] | None = None,
    date_range: dict[str, object] | None = None,
    output_mode: str = "chart",
) -> dict[str, object]:
    return {
        "workout_selector": workout_selector or {"type": "latest"},
        "x_metric": x_metric,
        "requested_metrics": list(metrics),
        "transform_hints": list(transforms),
        "date_range": date_range or {},
        "comparison_mode": comparison_mode,
        "layout_mode": layout_mode,
        "chart_kind": chart_kind,
        "output_mode": output_mode,
        "context_update": context_update or {"set_current_workout": False},
    }


def _visualization_intent(
    metrics: tuple[str, ...],
    *,
    x_metric: str = "elapsed_s",
    transforms: tuple[str, ...] = (),
    comparison_mode: str = "",
    layout_mode: str = "auto",
    chart_kind: str = "auto",
    workout_selector: dict[str, object] | None = None,
    context_update: dict[str, object] | None = None,
    date_range: dict[str, object] | None = None,
    output_mode: str = "chart",
) -> VisualizationIntent:
    return VisualizationIntent(
        workout_selector=workout_selector or {"type": "latest"},
        x_metric=x_metric,
        y_metrics=metrics,
        transforms=transforms,
        date_range=date_range or {},
        comparison_mode=comparison_mode,
        layout_mode=layout_mode,
        chart_kind=chart_kind,
        context_update=context_update or {"set_current_workout": False},
        output_mode=output_mode,
    )


def _visualization_client(intent: dict[str, object]) -> FakeLLMClient:
    return FakeLLMClient(
        {
            LLMOperation.INTENT_CLASSIFICATION: _classification(),
            LLMOperation.VISUALIZATION_INTENT: intent,
        }
    )


if __name__ == "__main__":
    unittest.main()
