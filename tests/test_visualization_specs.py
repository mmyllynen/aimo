from __future__ import annotations

import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from core.config import MapsConfig
from core.i18n import SupportedLanguage
from llm.operations import VisualizationIntent
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from visualization.datasets import dataset_request_from_metrics, resolve_datasets
from visualization.render import (
    DEFAULT_RENDER_HEIGHT,
    DEFAULT_RENDER_WIDTH,
    MARKER_POINT_LIMIT,
    Axis,
    Bar,
    BarChart,
    LineChart,
    LinePanel,
    MultiPanelLineChart,
    PieChart,
    PieSlice,
    RenderSeries,
    RouteMap,
    RouteMapTile,
    RouteElevationProfile,
    RouteElevationSample,
    RoutePoint,
    RoutePolyline,
    SocialImage,
    SocialImageStyle,
    _best_route_safe_rect,
    _chart_frame,
    _pie_radius,
    _show_markers,
    _axis,
    _fill_short_gaps,
    _format_tick,
    _prepare_render_series,
    _robust_axis,
    _scale_y,
    _time_axis,
    route_metric_color,
    route_map_viewport,
)
from visualization.pillow_renderer import (
    ElevationMarkerSpec,
    MapMarkerLabelSpec,
    PillowVisualizationRenderer,
    _boxes_overlap,
    _draw_social_polyline,
    _font,
    _grade_color,
    _elevation_point_at_distance,
    _grade_scale_box,
    _layout_elevation_marker_labels,
    _distance_tick_step,
    _map_marker_label_box,
    _offset_points,
    _place_map_marker_label,
    _point_at_route_distance,
    _route_km_markers,
    _route_overlay_height,
    _route_subtitle_lines,
    _visible_route_legend_count,
    _visible_waypoint_count,
)
from visualization.renderer import resolve_renderer
from visualization.tiles import TileCoord
from visualization.specs import (
    Encoding,
    MissingRenderableDataError,
    TransformNotApplicableError,
    UnsupportedColumnError,
    UnsupportedMarkError,
    UnsupportedTransformError,
    VisualizationSpec,
    compile_visualization_spec,
    visualization_validation_issue,
)
from visualization.service import (
    _aggregate_bars,
    _apply_rolling_average,
    _chart_subtitle,
    _color_hint,
    _effective_layout_mode,
    _explicit_smooth_window,
    _invert_y_axis,
    _metric_label,
    _bar_tick_format,
    _preferred_tile_zoom,
    _route_chart_subtitle,
    _route_color_domain,
    _route_color_metric_label,
    _route_color_status,
    _route_legend_title,
    _route_label,
    _route_polylines,
    _route_map_safe_rect,
    _route_waypoints,
    _should_render_metric_aggregate_bars,
    _tile_provider_configs,
    _transformed_rows,
    render_workout_visualization,
)
from visualization.service import _apply_normalization, _chart_title, _y_axis_label
from visualization.tiles import TileFetchConfig
from workflows.visualization import _apply_visualization_modifiers


class VisualizationSpecTests(unittest.TestCase):
    def test_route_map_can_render_png_tile_background(self) -> None:
        tile_content = _solid_png(256, 256, (171, 205, 239))

        rendered = PillowVisualizationRenderer().render_route_map_png(
            RouteMap(
                title="Route",
                routes=(
                    RoutePolyline(
                        label="route",
                        points=(
                            RoutePoint(latitude=60.1699, longitude=24.9384),
                            RoutePoint(latitude=60.1702, longitude=24.9390),
                        ),
                    ),
                ),
                tiles=(RouteMapTile(coord=TileCoord(z=12, x=2331, y=1185), content=tile_content),),
                tile_zoom=12,
                attribution="OpenStreetMap",
            )
        )

        with Image.open(BytesIO(rendered)) as image:
            self.assertEqual(image.convert("RGB").getpixel((160, 120)), (171, 205, 239))

    def test_renderer_resolves_to_pillow(self) -> None:
        self.assertEqual(resolve_renderer("route").name, "pillow")

    def test_pillow_renderer_renders_all_chart_types_as_png(self) -> None:
        renderer = PillowVisualizationRenderer()
        line = renderer.render_line_chart_png(
            LineChart(
                title="Line",
                x_values=(0.0, 1.0, 2.0),
                series=(RenderSeries(metric="pace", values=(5.0, 5.5, 5.2), label="Pace"),),
                x_label="Time",
                y_label="Pace",
            )
        )
        multi = renderer.render_multi_panel_line_chart_png(
            MultiPanelLineChart(
                title="Panels",
                x_values=(0.0, 1.0, 2.0),
                panels=(
                    LinePanel(RenderSeries(metric="heart_rate_bpm", values=(120.0, 130.0, 125.0), label="HR"), "HR"),
                    LinePanel(RenderSeries(metric="elevation_m", values=(40.0, 45.0, 42.0), label="Elevation"), "Elevation"),
                ),
            )
        )
        bar = renderer.render_bar_chart_png(
            BarChart(title="Bars", bars=(Bar(label="A", value=1.0), Bar(label="B", value=2.0)), x_label="Kind", y_label="Value")
        )
        pie = renderer.render_pie_chart_png(
            PieChart(title="Pie", slices=(PieSlice(label="A", value=1.0), PieSlice(label="B", value=2.0)), value_label="Share")
        )
        route = renderer.render_route_map_png(
            RouteMap(
                title="Route",
                routes=(
                    RoutePolyline(
                        label="route",
                        points=(
                            RoutePoint(latitude=60.1699, longitude=24.9384),
                            RoutePoint(latitude=60.1702, longitude=24.9390),
                        ),
                    ),
                ),
            )
        )

        for content, expected_size in (
            (line, (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT)),
            (multi, (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT)),
            (bar, (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT)),
            (pie, (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT)),
            (route, (DEFAULT_RENDER_WIDTH, DEFAULT_RENDER_HEIGHT)),
        ):
            with Image.open(BytesIO(content)) as decoded:
                self.assertEqual(decoded.format, "PNG")
                self.assertEqual(decoded.size, expected_size)

    def test_pillow_route_overlay_uses_dark_translucent_panel(self) -> None:
        content = PillowVisualizationRenderer().render_route_map_png(
            RouteMap(
                title="Route - Long Run",
                subtitle="2026-06-16 - Activity - 5.4 km",
                routes=(
                    RoutePolyline(
                        label="route",
                        points=(
                            RoutePoint(latitude=60.1699, longitude=24.9384),
                            RoutePoint(latitude=60.1702, longitude=24.9390),
                        ),
                    ),
                ),
            )
        )

        with Image.open(BytesIO(content)) as decoded:
            self.assertEqual(decoded.format, "PNG")
            red, green, blue = decoded.convert("RGB").getpixel((700, 96))
        self.assertLess(max(red, green, blue), 170)
        self.assertGreater(min(red, green, blue), 60)

    def test_social_style_block_updates_visualization_intent(self) -> None:
        intent = VisualizationIntent(
            workout_selector={"type": "latest"},
            x_metric="elapsed_s",
            y_metrics=("route",),
            transforms=(),
            date_range={},
            comparison_mode="",
            chart_kind="map",
            output_mode="social_image",
        )

        styled = _apply_visualization_modifiers(
            intent,
            "piirrä somekuva viimeisestä treenistä +poster\ntyyli: crop=top dim=35 filter=warm route=white route_size=large title=bottom stats=right panel=none",
        )

        self.assertEqual(styled.social_style["preset"], "poster")
        self.assertEqual(styled.social_style["crop"], "top")
        self.assertEqual(styled.social_style["dim"], 35)
        self.assertEqual(styled.social_style["filter"], "warm")
        self.assertEqual(styled.social_style["route"], "white")
        self.assertEqual(styled.social_style["route_size"], "large")
        self.assertEqual(styled.social_style["title"], "bottom")
        self.assertEqual(styled.social_style["stats"], "right")
        self.assertEqual(styled.social_style["panel"], "none")

    def test_social_inline_style_tokens_update_visualization_intent(self) -> None:
        intent = VisualizationIntent(
            workout_selector={"type": "latest"},
            x_metric="elapsed_s",
            y_metrics=("route",),
            transforms=(),
            date_range={},
            comparison_mode="",
            chart_kind="map",
            output_mode="social_image",
        )

        styled = _apply_visualization_modifiers(
            intent,
            "piirrä somekuva viimeisestä treenistä route=yellow dim=50 title=bottom",
        )

        self.assertEqual(styled.social_style["route"], "yellow")
        self.assertEqual(styled.social_style["dim"], 50)
        self.assertEqual(styled.social_style["title"], "bottom")

    def test_social_plus_metric_sets_route_color_metric(self) -> None:
        intent = VisualizationIntent(
            workout_selector={"type": "latest"},
            x_metric="elapsed_s",
            y_metrics=("route",),
            transforms=(),
            date_range={},
            comparison_mode="",
            chart_kind="map",
            output_mode="social_image",
        )

        styled = _apply_visualization_modifiers(
            intent,
            "piirrä somekuva viimeisestä treenistä +hr route=yellow",
        )

        self.assertEqual(styled.route_color_metric, "heart_rate_bpm")
        self.assertEqual(styled.social_style["route"], "yellow")

    def test_social_route_shadow_offset_helper_moves_colored_layer(self) -> None:
        self.assertEqual(_offset_points([(1.0, 2.0), (3.5, 4.5)], 3, 3), [(4.0, 5.0), (6.5, 7.5)])

    def test_social_polyline_draws_segments_and_round_joints(self) -> None:
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")

        _draw_social_polyline(draw, [(5, 5), (20, 5), (20, 20)], (255, 200, 0, 255), width=6)

        self.assertEqual(image.getpixel((12, 5))[3], 255)
        self.assertEqual(image.getpixel((20, 5))[3], 255)
        self.assertEqual(image.getpixel((20, 14))[3], 255)

    def test_pillow_social_image_accepts_custom_style(self) -> None:
        content = PillowVisualizationRenderer().render_social_image_png(
            SocialImage(
                title="Styled run",
                routes=(
                    RoutePolyline(
                        label="route",
                        points=(
                            RoutePoint(latitude=60.1, longitude=24.9),
                            RoutePoint(latitude=60.11, longitude=24.91),
                            RoutePoint(latitude=60.12, longitude=24.92),
                        ),
                    ),
                ),
                stats=(),
                background_image=_solid_png(20, 30, (180, 210, 240)),
                style=SocialImageStyle(
                    background_crop="top",
                    background_dim=35,
                    background_filter="warm",
                    route_color="white",
                    route_size="large",
                    route_shadow=False,
                    route_markers=False,
                    title_position="bottom",
                    panel_style="none",
                    font="mono",
                ),
                width=320,
                height=320,
            )
        )

        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.size, (320, 320))

    def test_pillow_social_image_dims_map_background(self) -> None:
        renderer = PillowVisualizationRenderer()
        route = RoutePolyline(
            label="route",
            points=(
                RoutePoint(latitude=60.1, longitude=24.9),
                RoutePoint(latitude=60.11, longitude=24.91),
            ),
        )
        base = renderer.render_social_image_png(
            SocialImage(
                title="Map",
                routes=(route,),
                stats=(),
                map_background=RouteMap(title="Map", routes=(route,), width=320, height=320),
                style=SocialImageStyle(background_dim=0, title_position="hide", route_markers=False),
                width=320,
                height=320,
            )
        )
        dimmed = renderer.render_social_image_png(
            SocialImage(
                title="Map",
                routes=(route,),
                stats=(),
                map_background=RouteMap(title="Map", routes=(route,), width=320, height=320),
                style=SocialImageStyle(background_dim=50, title_position="hide", route_markers=False),
                width=320,
                height=320,
            )
        )

        base_pixels = Image.open(BytesIO(base)).convert("RGB")
        dimmed_pixels = Image.open(BytesIO(dimmed)).convert("RGB")
        base_avg = sum(sum(base_pixels.getpixel((x, y))) for y in range(base_pixels.height) for x in range(base_pixels.width)) / (base_pixels.width * base_pixels.height)
        dimmed_avg = sum(sum(dimmed_pixels.getpixel((x, y))) for y in range(dimmed_pixels.height) for x in range(dimmed_pixels.width)) / (
            dimmed_pixels.width * dimmed_pixels.height
        )
        self.assertLess(dimmed_avg, base_avg)

    def test_social_image_can_color_route_by_heart_rate_without_legend(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w", title="Run", duration_s=120, distance_km=1.0),
            (
                WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.17, longitude=24.94, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.18, longitude=24.95, heart_rate_bpm=140),
                WorkoutPointRecord(workout_id="w", point_index=2, latitude=60.19, longitude=24.96, heart_rate_bpm=160),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route", "avg_hr_bpm"),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
                output_mode="social_image",
                route_color_metric="heart_rate_bpm",
                social_style={"route": "yellow"},
            ),
        )

        self.assertEqual(artifact.metadata["social_route_color_metric"], "heart_rate_bpm")
        self.assertEqual(artifact.metadata["social_route_color_status"], "ok")
        self.assertEqual(artifact.rendered_metrics, ("avg_hr_bpm",))

    def test_route_map_title_subtitle_and_legend_label_are_user_friendly(self) -> None:
        workout = _workout(
            workout_id="workout-c726097d",
            title="Sipoo Running",
            start_time_local="2026-06-16T18:34:00+03:00",
            local_date="2026-06-16",
            distance_km=5.4,
            duration_s=2016,
            avg_hr_bpm=124,
        )

        self.assertEqual(_route_chart_subtitle(workout, language=SupportedLanguage.FI), "16/6/2026 18:34 - 5.4 km - 33min 36s - Keskisyke 124")
        self.assertEqual(_route_label(workout, "fallback"), "16/6/2026 18:34 5.4 km")

        utc_workout = _workout(
            workout_id="workout-c726097d",
            title="Sipoo Running",
            start_time_local="2026-06-16T03:27:42Z",
            local_date="2026-06-16",
            distance_km=5.4,
            duration_s=2016,
            avg_hr_bpm=124,
        )

        self.assertEqual(_route_chart_subtitle(utc_workout, language=SupportedLanguage.FI), "16/6/2026 6:27 - 5.4 km - 33min 36s - Keskisyke 124")
        self.assertEqual(_route_label(utc_workout, "fallback"), "16/6/2026 6:27 5.4 km")

        route_with_ascent = _workout(
            workout_id="workout-route",
            title="Juhannusreitti",
            distance_km=23.9,
            ascent_m=276,
        )

        self.assertEqual(_route_chart_subtitle(route_with_ascent, language=SupportedLanguage.FI), "23.9 km - nousua 276 m")

    def test_route_map_can_color_single_route_by_heart_rate(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w", title="Run", duration_s=120, distance_km=1.0),
            (
                WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.17, longitude=24.94, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.18, longitude=24.95, heart_rate_bpm=140),
                WorkoutPointRecord(workout_id="w", point_index=2, latitude=60.19, longitude=24.96, heart_rate_bpm=160),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route", "heart_rate_bpm"),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
                route_color_metric="heart_rate_bpm",
            ),
        )

        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("route", "heart_rate_bpm"))
        self.assertEqual(artifact.metadata["route_color_metric"], "heart_rate_bpm")
        self.assertEqual(artifact.metadata["route_color_status"], "ok")

    def test_route_map_renders_gpx_waypoints_by_default_and_can_hide_them(self) -> None:
        workout = _workout(
            workout_id="w",
            title="Route",
            metadata={
                "waypoints": [
                    {"latitude": 60.175, "longitude": 24.945, "name": "Info", "comment": "Aid station", "type": "INFO"},
                    {"latitude": "bad", "longitude": 24.950, "name": "Ignored"},
                ]
            },
        )
        points = (
            WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.17, longitude=24.94),
            WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.18, longitude=24.95),
        )
        base_intent = VisualizationIntent(
            workout_selector={"type": "latest"},
            x_metric="longitude",
            y_metrics=("route",),
            transforms=(),
            date_range={},
            comparison_mode="",
            chart_kind="map",
        )

        shown = render_workout_visualization(workout, points, base_intent)
        hidden = render_workout_visualization(
            workout,
            points,
            VisualizationIntent(
                workout_selector=base_intent.workout_selector,
                x_metric=base_intent.x_metric,
                y_metrics=base_intent.y_metrics,
                transforms=base_intent.transforms,
                date_range=base_intent.date_range,
                comparison_mode=base_intent.comparison_mode,
                chart_kind=base_intent.chart_kind,
                social_style={"waypoints": False},
            ),
        )

        self.assertEqual(shown.metadata["waypoint_count"], 1)
        self.assertEqual(shown.metadata["waypoints_rendered"], 1)
        self.assertEqual(shown.metadata["waypoint_status"], "rendered")
        self.assertEqual(hidden.metadata["waypoint_count"], 1)
        self.assertEqual(hidden.metadata["waypoints_rendered"], 0)
        self.assertEqual(hidden.metadata["waypoint_status"], "hidden_by_modifier")

    def test_route_map_hides_waypoints_for_multiple_routes(self) -> None:
        workout = _workout(
            workout_id="w",
            title="Routes",
            metadata={"waypoints": [{"latitude": 60.175, "longitude": 24.945, "comment": "Aid station", "type": "INFO"}]},
        )
        artifact = render_workout_visualization(
            workout,
            (
                WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.17, longitude=24.94),
                WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.18, longitude=24.95),
                WorkoutPointRecord(workout_id="other", point_index=0, latitude=60.19, longitude=24.96),
                WorkoutPointRecord(workout_id="other", point_index=1, latitude=60.20, longitude=24.97),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route",),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
            ),
            comparison_workouts=(_workout(workout_id="other", title="Other"),),
        )

        self.assertEqual(artifact.metadata["waypoint_count"], 1)
        self.assertEqual(artifact.metadata["waypoints_rendered"], 0)
        self.assertEqual(artifact.metadata["waypoint_status"], "multi_route_hidden")

    def test_route_waypoints_use_comment_label_type_and_distance_from_start(self) -> None:
        workout = _workout(
            workout_id="w",
            metadata={
                "waypoints": [
                    {"latitude": 60.010, "longitude": 24.0, "name": "Checkpoint", "comment": "Maalialue", "type": "CHECKPOINT"},
                    {"latitude": 60.005, "longitude": 24.0, "name": "Info", "comment": "Risteys", "type": "INFO"},
                ]
            },
        )
        routes = (
            RoutePolyline(
                label="route",
                points=(
                    RoutePoint(latitude=60.0, longitude=24.0),
                    RoutePoint(latitude=60.01, longitude=24.0),
                ),
            ),
        )

        waypoints = _route_waypoints(workout, routes)

        self.assertEqual(len(waypoints), 2)
        self.assertEqual(waypoints[0].label, "Risteys")
        self.assertEqual(waypoints[0].waypoint_type, "INFO")
        self.assertAlmostEqual(waypoints[0].distance_km or 0.0, 0.6, places=1)
        self.assertEqual(waypoints[1].label, "Maalialue")
        self.assertGreater(waypoints[1].distance_km or 0.0, waypoints[0].distance_km or 0.0)

    def test_route_map_elevation_overlay_metadata_for_single_route(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w", title="Route"),
            (
                WorkoutPointRecord(workout_id="w", point_index=0, distance_km=0.0, latitude=60.0, longitude=24.0, elevation_m=10),
                WorkoutPointRecord(workout_id="w", point_index=1, distance_km=1.0, latitude=60.01, longitude=24.0, elevation_m=30),
                WorkoutPointRecord(workout_id="w", point_index=2, distance_km=2.0, latitude=60.02, longitude=24.0, elevation_m=20),
                WorkoutPointRecord(workout_id="w", point_index=3, distance_km=3.0, latitude=60.03, longitude=24.0, elevation_m=50),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route",),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
            ),
        )

        self.assertEqual(artifact.metadata["elevation_overlay_status"], "rendered")
        self.assertEqual(artifact.metadata["elevation_overlay_min_m"], 10)
        self.assertEqual(artifact.metadata["elevation_overlay_max_m"], 50)

    def test_route_map_elevation_overlay_can_be_hidden_and_is_hidden_for_multi_route(self) -> None:
        points = (
            WorkoutPointRecord(workout_id="w", point_index=0, distance_km=0.0, latitude=60.0, longitude=24.0, elevation_m=10),
            WorkoutPointRecord(workout_id="w", point_index=1, distance_km=1.0, latitude=60.01, longitude=24.0, elevation_m=30),
            WorkoutPointRecord(workout_id="w", point_index=2, distance_km=2.0, latitude=60.02, longitude=24.0, elevation_m=20),
            WorkoutPointRecord(workout_id="other", point_index=0, distance_km=0.0, latitude=60.1, longitude=24.1, elevation_m=15),
            WorkoutPointRecord(workout_id="other", point_index=1, distance_km=1.0, latitude=60.11, longitude=24.1, elevation_m=35),
            WorkoutPointRecord(workout_id="other", point_index=2, distance_km=2.0, latitude=60.12, longitude=24.1, elevation_m=25),
        )
        hidden = render_workout_visualization(
            _workout(workout_id="w", title="Route"),
            points[:3],
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route",),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
                social_style={"elevation_overlay": False},
            ),
        )
        multi = render_workout_visualization(
            _workout(workout_id="w", title="Routes"),
            points,
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="longitude",
                y_metrics=("route",),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="map",
            ),
            comparison_workouts=(_workout(workout_id="other", title="Other"),),
        )

        self.assertEqual(hidden.metadata["elevation_overlay_status"], "hidden_by_modifier")
        self.assertEqual(multi.metadata["elevation_overlay_status"], "multi_route_hidden")

    def test_grade_color_scale_marks_easy_descents_and_hard_climbs(self) -> None:
        self.assertEqual(_grade_color(-0.12), (126, 34, 206))
        self.assertEqual(_grade_color(-0.06), (37, 99, 235))
        self.assertEqual(_grade_color(-0.01), (22, 163, 74))
        self.assertEqual(_grade_color(0.02), (203, 213, 225))
        self.assertEqual(_grade_color(0.06), (250, 204, 21))
        self.assertEqual(_grade_color(0.10), (249, 115, 22))
        self.assertEqual(_grade_color(0.15), (220, 38, 38))
        self.assertNotEqual(_grade_color(-0.08), _grade_color(-0.06))
        self.assertNotEqual(_grade_color(0.08), _grade_color(0.10))

    def test_elevation_marker_helpers_interpolate_waypoint_height_and_safe_area(self) -> None:
        profile = RouteElevationProfile(
            samples=(
                RouteElevationSample(distance_km=0.0, elevation_m=10),
                RouteElevationSample(distance_km=1.0, elevation_m=30),
                RouteElevationSample(distance_km=2.0, elevation_m=20),
            ),
            min_index=0,
            max_index=1,
        )

        marker = _elevation_point_at_distance(profile, 0.5, [(0.0, 100.0), (100.0, 50.0), (200.0, 75.0)])
        safe_rect = _route_map_safe_rect(1920, 1080, profile)

        self.assertEqual(marker, (50.0, 75.0, 20.0))
        self.assertEqual(safe_rect, (48, 156, 1872, 822))
        self.assertIsNone(_route_map_safe_rect(1920, 1080, None))

    def test_elevation_label_layout_avoids_grade_scale_and_nearby_labels(self) -> None:
        image = Image.new("RGBA", (900, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")
        grade_scale = _grade_scale_box(600, 20, scale=1)
        label_top = grade_scale[3] + 8
        labels = _layout_elevation_marker_labels(
            draw,
            (
                ElevationMarkerSpec("Lähtö", 71, 575, 0, 0.0, "right"),
                ElevationMarkerSpec("Maali", 70, 875, 1, 24.0, "left"),
                ElevationMarkerSpec("Risteys", 40, 360, 2, 9.7, "right"),
                ElevationMarkerSpec("Korkein kohta", 102, 365, 3, 10.0, "right"),
            ),
            label_bounds=(10, label_top, 890, label_top + 84),
            scale=1,
        )

        boxes = [label.box for label in labels]
        by_text = {label.text: label for label in labels}
        self.assertGreaterEqual(len(labels), 3)
        self.assertIn("Maali 70 m", by_text)
        self.assertEqual(by_text["Maali 70 m"].box[2], by_text["Maali 70 m"].spec.x)
        self.assertIn("Risteys 40 m", by_text)
        self.assertEqual(by_text["Risteys 40 m"].box[0], by_text["Risteys 40 m"].spec.x)
        for index, box in enumerate(boxes):
            self.assertFalse(_boxes_overlap(box, grade_scale, padding=0))
            for other in boxes[index + 1 :]:
                self.assertFalse(_boxes_overlap(box, other, padding=0))

    def test_route_km_marker_helpers_use_distance_ticks_and_interpolation(self) -> None:
        self.assertEqual(_distance_tick_step(4.9), 1.0)
        self.assertEqual(_distance_tick_step(12.0), 2.0)
        self.assertEqual(_distance_tick_step(24.0), 5.0)
        self.assertEqual(_distance_tick_step(80.0), 10.0)
        self.assertEqual(_distance_tick_step(120.0), 20.0)

        point = _point_at_route_distance(5.0, (0.0, 10.0), [(0.0, 0.0), (100.0, 0.0)])
        route = RoutePolyline(
            label="route",
            points=(
                RoutePoint(latitude=60.0, longitude=24.0),
                RoutePoint(latitude=60.09, longitude=24.0),
                RoutePoint(latitude=60.18, longitude=24.0),
            ),
        )
        markers = _route_km_markers(route, [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)])

        self.assertEqual(point, (50.0, 0.0))
        self.assertGreaterEqual(len(markers), 1)
        self.assertLess(markers[0][0], 20.0)

    def test_map_marker_label_layout_tries_fallback_positions(self) -> None:
        image = Image.new("RGBA", (300, 160), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")
        waypoint = MapMarkerLabelSpec("Waypoint", (100.0, 80.0), (124, 58, 237))
        km = MapMarkerLabelSpec("5 km", (104.0, 82.0), (59, 130, 246), required=False)
        waypoint_box = _map_marker_label_box(draw, waypoint, "right_up", bounds=(0, 0, 300, 160), scale=1)

        placed = _place_map_marker_label(draw, km, bounds=(0, 0, 300, 160), occupied=[waypoint_box], scale=1)

        self.assertIsNotNone(waypoint_box)
        self.assertIsNotNone(placed)
        self.assertFalse(_boxes_overlap(placed, waypoint_box, padding=3))

    def test_render_workout_visualization_accepts_square_output_size_for_line_chart(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w", title="Run", duration_s=120, distance_km=1.0),
            (
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=140),
                WorkoutPointRecord(workout_id="w", point_index=2, elapsed_s=120, heart_rate_bpm=160),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="elapsed_s",
                y_metrics=("heart_rate_bpm",),
                transforms=(),
                date_range={},
                comparison_mode="",
                chart_kind="line",
                render_width=1080,
                render_height=1080,
            ),
        )

        with Image.open(BytesIO(artifact.content)) as image:
            self.assertEqual(image.size, (1080, 1080))
        self.assertEqual(artifact.metadata["render_width"], 1080)
        self.assertEqual(artifact.metadata["render_height"], 1080)

    def test_route_color_status_allows_multiple_routes_with_shared_data_scale(self) -> None:
        routes = (
            RoutePolyline(
                label="first",
                color_metric="heart_rate_bpm",
                points=(RoutePoint(60.1, 24.9, color_value=120), RoutePoint(60.2, 25.0, color_value=130)),
            ),
            RoutePolyline(
                label="second",
                color_metric="heart_rate_bpm",
                points=(RoutePoint(60.3, 25.1, color_value=140), RoutePoint(60.4, 25.2, color_value=150)),
            ),
        )

        self.assertEqual(_route_color_status(routes, route_color_metric="heart_rate_bpm"), "ok")

    def test_route_map_legend_title_is_localized_by_route_count(self) -> None:
        single = (RoutePolyline(label="route", points=()),)
        multiple = (RoutePolyline(label="route 1", points=()), RoutePolyline(label="route 2", points=()))

        self.assertEqual(_route_legend_title(single, language=SupportedLanguage.FI), "Reitti")
        self.assertEqual(_route_legend_title(single, language=SupportedLanguage.EN), "Route")
        self.assertEqual(_route_legend_title(multiple, language=SupportedLanguage.FI), "Treenit")
        self.assertEqual(_route_legend_title(multiple, language=SupportedLanguage.EN), "Workouts")
        self.assertEqual(_route_color_metric_label("heart_rate_bpm", language=SupportedLanguage.FI), "Syke")
        self.assertEqual(_route_color_metric_label("heart_rate_bpm", language=SupportedLanguage.EN), "Heart rate")
        self.assertEqual(_route_color_metric_label("pace_s_per_km", language=SupportedLanguage.FI), "Vauhti (min/km)")
        self.assertEqual(_route_color_metric_label("pace_s_per_km", language=SupportedLanguage.EN), "Pace (min/km)")

    def test_pillow_route_legend_shows_up_to_twenty_rows_when_space_allows(self) -> None:
        self.assertEqual(_visible_route_legend_count(9, DEFAULT_RENDER_HEIGHT * 2, scale=2), 9)
        self.assertEqual(_visible_route_legend_count(25, DEFAULT_RENDER_HEIGHT * 2, scale=2), 20)
        self.assertEqual(_visible_route_legend_count(1, DEFAULT_RENDER_HEIGHT * 2, scale=2), 0)
        self.assertGreater(_visible_waypoint_count(2, DEFAULT_RENDER_HEIGHT * 2, 0, scale=2), 0)
        self.assertEqual(_route_overlay_height(color_scale_only=False, visible_route_count=0, visible_waypoint_count=0, scale=2), 0)

    def test_pillow_route_subtitle_wraps_structured_summary_only_when_needed(self) -> None:
        draw = ImageDraw.Draw(Image.new("RGBA", (900, 300)))
        font = _font(24)
        subtitle = "16/6/2026 6:27 - 5.5 km - 33min 36s - Keskisyke 124"
        full_width = draw.textbbox((0, 0), subtitle, font=font)[2]
        wrapped_width = max(
            draw.textbbox((0, 0), "16/6/2026 6:27 - 5.5 km", font=font)[2],
            draw.textbbox((0, 0), "33min 36s - Keskisyke 124", font=font)[2],
        )

        self.assertEqual(_route_subtitle_lines(draw, subtitle, full_width + 20, font), (subtitle,))
        self.assertEqual(
            _route_subtitle_lines(draw, subtitle, wrapped_width + 20, font),
            ("16/6/2026 6:27 - 5.5 km", "33min 36s - Keskisyke 124"),
        )

    def test_route_map_safe_area_can_use_right_side_below_small_legend(self) -> None:
        route_x = (0.0, 100.0)
        route_y = (0.0, 10.0)

        rect = _best_route_safe_rect(route_x, route_y, width=1080, height=1080)

        self.assertEqual(rect, (48, 156, 1032, 1052))

    def test_route_map_viewport_uses_map_first_safe_area(self) -> None:
        route = RoutePolyline(
            label="route",
            points=(
                RoutePoint(latitude=60.2928511518985, longitude=25.304258912801743),
                RoutePoint(latitude=60.303914258256555, longitude=25.33885865472257),
            ),
        )

        viewport = route_map_viewport((route,), width=900, height=520)

        self.assertLess(viewport.x_domain[0], viewport.x_domain[1])
        self.assertLess(viewport.y_domain[0], viewport.y_domain[1])
        self.assertLess(viewport.x_domain[1] - viewport.x_domain[0], 0.00025)

    def test_route_map_tile_zoom_targets_native_pixel_density(self) -> None:
        route = RoutePolyline(
            label="route",
            points=(
                RoutePoint(latitude=60.2928511518985, longitude=25.304258912801743),
                RoutePoint(latitude=60.303914258256555, longitude=25.33885865472257),
            ),
        )
        viewport = route_map_viewport((route,), width=900, height=520)

        zoom = _preferred_tile_zoom(viewport.x_domain, viewport.y_domain, width=900, config=TileFetchConfig(cache_root=Path(".")))

        self.assertEqual(zoom, 15)

    def test_maptiler_tile_provider_uses_separate_cache_and_512_tiles(self) -> None:
        providers = _tile_provider_configs(Path("cache/osm_tiles"), MapsConfig(provider="maptiler", maptiler_api_key="secret", maptiler_map_id="streets-v4"))

        self.assertEqual(providers[0].name, "maptiler")
        self.assertEqual(providers[0].background, "maptiler_tiles")
        self.assertEqual(providers[0].tile_size, 512)
        self.assertEqual(providers[0].config.cache_root, Path("cache/maptiler_tiles/streets-v4"))
        self.assertIn("api.maptiler.com/maps/streets-v4", providers[0].config.url_template)
        self.assertNotIn("secret", str(providers[0].config.cache_root))
        self.assertEqual(providers[1].name, "openstreetmap")

    def test_dense_series_hides_markers_without_metric_specific_rule(self) -> None:
        dense = tuple(float(index) for index in range(MARKER_POINT_LIMIT + 1))
        sparse = tuple(float(index) for index in range(MARKER_POINT_LIMIT))

        self.assertFalse(_show_markers(dense, dense))
        self.assertTrue(_show_markers(sparse, sparse))

    def test_numeric_axis_uses_nice_integer_ticks_for_data_range(self) -> None:
        axis = _axis((89, 143), target_ticks=6)

        self.assertEqual(axis.domain, (80, 150))
        self.assertEqual(axis.ticks, (80, 90, 100, 110, 120, 130, 140, 150))
        self.assertEqual([_format_tick(value) for value in axis.ticks], ["80", "90", "100", "110", "120", "130", "140", "150"])

    def test_numeric_axis_uses_decimal_ticks_only_when_scale_requires_it(self) -> None:
        axis = _axis((4.8, 6.2), target_ticks=6)

        self.assertEqual(axis.domain, (4.5, 6.5))
        self.assertEqual(axis.ticks, (4.5, 5.0, 5.5, 6.0, 6.5))
        self.assertEqual([_format_tick(value) for value in axis.ticks], ["4.5", "5", "5.5", "6", "6.5"])

    def test_time_axis_uses_duration_ticks(self) -> None:
        axis = _time_axis((0, 3300), target_ticks=6)

        self.assertEqual(axis.domain, (0.0, 3600.0))
        self.assertEqual(axis.ticks, (0.0, 600.0, 1200.0, 1800.0, 2400.0, 3000.0, 3600.0))
        self.assertEqual([_format_tick(value, tick_format="duration") for value in axis.ticks], ["0:00", "10:00", "20:00", "30:00", "40:00", "50:00", "1:00"])

    def test_pace_ticks_render_as_minutes_per_kilometer(self) -> None:
        self.assertEqual(_format_tick(330, tick_format="pace"), "5:30")
        self.assertEqual(_format_tick(360, tick_format="pace"), "6:00")

    def test_pace_metric_profile_cleans_point_dataset_outliers(self) -> None:
        manifest = resolve_datasets(
            dataset_request_from_metrics(
                x_metric="elapsed_s",
                y_metrics=("pace_s_per_km",),
                transforms=(),
            ),
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, pace_s_per_km=360),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, pace_s_per_km=365),
                WorkoutPointRecord(workout_id="w", point_index=2, elapsed_s=120, pace_s_per_km=1104),
                WorkoutPointRecord(workout_id="w", point_index=3, elapsed_s=180, pace_s_per_km=370),
                WorkoutPointRecord(workout_id="w", point_index=4, elapsed_s=240, pace_s_per_km=375),
            ),
        )

        dataset = manifest.dataset("workout_points")
        self.assertIsNotNone(dataset)
        values = tuple(row["pace_s_per_km"] for row in dataset.rows)
        self.assertEqual(values, (365.0, 367.5, 370.0, 372.5, 375.0))
        pace_column = next(column for column in dataset.columns if column.column_id == "pace_s_per_km")
        self.assertEqual(pace_column.max_value, 375.0)

    def test_route_pace_color_uses_cleaned_values_and_robust_domain(self) -> None:
        routes = _route_polylines(
            [
                WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.10, longitude=24.90, pace_s_per_km=360),
                WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.11, longitude=24.91, pace_s_per_km=365),
                WorkoutPointRecord(workout_id="w", point_index=2, latitude=60.12, longitude=24.92, pace_s_per_km=1104),
                WorkoutPointRecord(workout_id="w", point_index=3, latitude=60.13, longitude=24.93, pace_s_per_km=370),
                WorkoutPointRecord(workout_id="w", point_index=4, latitude=60.14, longitude=24.94, pace_s_per_km=375),
            ],
            route_color_metric="pace_s_per_km",
        )

        self.assertEqual(tuple(point.color_value for point in routes[0].points), (365.0, 367.5, 370.0, 372.5, 375.0))
        domain = _route_color_domain(routes, "pace_s_per_km")
        self.assertIsNotNone(domain)
        self.assertLess(domain[1], 400)

    def test_route_color_direction_is_metric_metadata_driven(self) -> None:
        fast_color = route_metric_color(330, (300, 600), direction="descending")
        slow_color = route_metric_color(570, (300, 600), direction="descending")

        self.assertGreater(fast_color[0], slow_color[0])
        self.assertLess(fast_color[2], slow_color[2])

    def test_percentage_ticks_render_with_percent_suffix(self) -> None:
        self.assertEqual(_format_tick(25, tick_format="percentage"), "25%")
        self.assertEqual(_format_tick(12.5, tick_format="percentage"), "12.5%")

    def test_chart_frame_reserves_right_sidebar(self) -> None:
        frame = _chart_frame(900, 520)

        self.assertGreaterEqual(frame.sidebar_left, 650)
        self.assertLess(frame.plot_right, frame.sidebar_left)
        self.assertGreaterEqual(frame.sidebar_right - frame.sidebar_left, 220)
        self.assertEqual(frame.sidebar_top, 0)
        self.assertEqual(frame.sidebar_right, 899)
        self.assertEqual(frame.sidebar_bottom, 519)

    def test_pie_radius_uses_available_plot_area(self) -> None:
        frame = _chart_frame(900, 520)
        center_x = (frame.plot_left + frame.plot_right) // 2
        center_y = (frame.plot_top + frame.plot_bottom) // 2 + 8

        self.assertGreater(_pie_radius(frame, center_x, center_y, scale=1, has_value_label=True), 170)

    def test_inverted_y_scale_places_smaller_values_higher(self) -> None:
        normal_fast = _scale_y(300, (300, 600), 100, 0, invert=False)
        normal_slow = _scale_y(600, (300, 600), 100, 0, invert=False)
        inverted_fast = _scale_y(300, (300, 600), 100, 0, invert=True)
        inverted_slow = _scale_y(600, (300, 600), 100, 0, invert=True)

        self.assertGreater(normal_fast, normal_slow)
        self.assertLess(inverted_fast, inverted_slow)

    def test_time_per_distance_metrics_invert_y_axis(self) -> None:
        self.assertTrue(_invert_y_axis("pace_s_per_km"))
        self.assertFalse(_invert_y_axis("heart_rate_bpm"))
        self.assertFalse(_invert_y_axis("elevation_m"))

    def test_robust_axis_excludes_large_outlier_from_render_domain(self) -> None:
        axis = _robust_axis((320, 330, 340, 350, 360, 370, 380, 390, 400, 300000), target_ticks=4)

        self.assertTrue(axis.clipped)
        self.assertLess(axis.domain[1], 1000)

    def test_robust_axis_does_not_clip_normal_edge_values(self) -> None:
        axis = _robust_axis((90, 95, 105, 115, 125, 132, 136, 139, 141, 143, 145, 147), target_ticks=4)

        self.assertFalse(axis.clipped)
        self.assertLessEqual(axis.domain[0], 90)

    def test_dense_rough_series_is_auto_smoothed_for_rendering(self) -> None:
        values = tuple(300.0 if index % 2 == 0 else 500.0 for index in range(180))

        series = _prepare_render_series(
            RenderSeries(metric="rough", values=values),
            Axis(domain=(250.0, 550.0), ticks=(300.0, 400.0, 500.0)),
        )

        self.assertTrue(series.smoothed)
        self.assertNotEqual(series.values, values)

    def test_short_gaps_are_filled_for_smoothed_rendering(self) -> None:
        filled = _fill_short_gaps((1.0, None, None, 4.0), max_gap=2)

        self.assertEqual(filled, (1.0, 2.0, 3.0, 4.0))

    def test_edge_and_long_gaps_are_not_filled_for_rendering(self) -> None:
        self.assertEqual(_fill_short_gaps((None, 1.0, 2.0), max_gap=2), (None, 1.0, 2.0))
        self.assertEqual(_fill_short_gaps((1.0, None, None, None, 5.0), max_gap=2), (1.0, None, None, None, 5.0))

    def test_axis_can_tighten_after_auto_smoothing(self) -> None:
        values = tuple(300.0 + ((index * 37) % 170) for index in range(180)) + (300000.0,)
        preliminary_axis = _robust_axis(values, target_ticks=5)
        series = _prepare_render_series(RenderSeries(metric="rough", values=values), preliminary_axis)
        final_axis = _robust_axis(series.values, target_ticks=5)

        self.assertTrue(series.clipped)
        self.assertTrue(series.smoothed)
        self.assertLessEqual(final_axis.domain[1], preliminary_axis.domain[1])

    def test_dense_smooth_series_is_not_auto_smoothed_for_rendering(self) -> None:
        values = tuple(120.0 + index * 0.05 for index in range(180))

        series = _prepare_render_series(
            RenderSeries(metric="smooth", values=values),
            Axis(domain=(120.0, 130.0), ticks=(120.0, 125.0, 130.0)),
        )

        self.assertFalse(series.smoothed)

    def test_dataset_request_normalizes_canonical_metric_ids(self) -> None:
        request = dataset_request_from_metrics(
            x_metric=" ELAPSED_S ",
            y_metrics=(" HEART_RATE_BPM ", "PACE_S_PER_KM"),
            transforms=("normalize_to_primary_range",),
        )

        self.assertEqual(request.x_metric, "elapsed_s")
        self.assertEqual(request.metrics, ("heart_rate_bpm", "pace_s_per_km"))
        self.assertEqual(request.transforms, ("normalize_to_primary_range",))

    def test_compile_spec_selects_line_mark_from_point_dataset(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("heart_rate_bpm",), transforms=())
        manifest = resolve_datasets(
            request,
            points=(WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),),
        )

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "line")
        self.assertEqual(spec.x.dataset_id, "workout_points")
        self.assertEqual(spec.y[0].column_id, "heart_rate_bpm")

    def test_compile_spec_selects_bar_mark_from_nominal_dataset_axis(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_zone_seconds",),
            transforms=(),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="Easy", upper_bpm=124),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="Steady", lower_bpm=125),
            ),
        )

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(spec.x.column_id, "zone_label")
        self.assertEqual(spec.y[0].column_id, "heart_rate_zone_seconds")

    def test_compile_spec_prefers_nominal_axis_when_requested_x_is_also_y_metric(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="heart_rate_zone_seconds",
            y_metrics=("heart_rate_zone_seconds",),
            transforms=("aggregate_sum",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="pk1", upper_bpm=124),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="pk2", lower_bpm=125),
            ),
        )

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(spec.x.column_id, "zone_label")
        self.assertEqual(spec.y[0].column_id, "heart_rate_zone_seconds")

    def test_percentage_transform_is_valid_for_categorical_numeric_bars(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="heart_rate_zone_seconds",
            y_metrics=("heart_rate_zone_seconds",),
            transforms=("as_percentage_of_total",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
                WorkoutPointRecord(workout_id="w", point_index=2, elapsed_s=180, heart_rate_bpm=140),
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="pk1", upper_bpm=124),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="pk2", lower_bpm=125, upper_bpm=134),
                HeartRateZoneRecord(user_id="u", zone_key="z3", label="vk1", lower_bpm=135),
            ),
        )

        spec = compile_visualization_spec(request, manifest)
        rows = _transformed_rows(spec, manifest.dataset("hr_zone_distribution"))

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(_bar_tick_format(spec), "percentage")
        self.assertEqual([round(row["heart_rate_zone_seconds"], 1) for row in rows], [33.3, 66.7, 0.0])
        self.assertEqual([row["color_hint"] for row in rows], ["blue", "yellow", "red"])

    def test_compile_spec_selects_pie_mark_from_explicit_chart_kind_for_categorical_values(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="heart_rate_zone_seconds",
            y_metrics=("heart_rate_zone_seconds",),
            transforms=("as_percentage_of_total",),
            chart_kind="pie",
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="Easy", upper_bpm=124),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="Steady", lower_bpm=125),
            ),
        )

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "pie")
        self.assertEqual(spec.x.column_id, "zone_label")
        self.assertEqual(spec.y[0].column_id, "heart_rate_zone_seconds")

    def test_compile_spec_rejects_pie_mark_for_continuous_axis(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm",),
            transforms=(),
            chart_kind="pie",
        )
        manifest = resolve_datasets(
            request,
            points=(WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),),
        )

        with self.assertRaises(TransformNotApplicableError):
            compile_visualization_spec(request, manifest)

    def test_percentage_transform_is_rejected_for_line_charts(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm",),
            transforms=("as_percentage_of_total",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
            ),
        )

        with self.assertRaises(TransformNotApplicableError):
            compile_visualization_spec(request, manifest)

    def test_compile_spec_selects_workout_summary_dataset_for_summary_metric(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("duration_s",), transforms=())
        manifest = resolve_datasets(request, points=(), workout=_workout(duration_s=3600, distance_km=10.0))

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(spec.x.dataset_id, "workout_summary")
        self.assertEqual(spec.x.column_id, "workout_title")
        self.assertEqual(spec.y[0].column_id, "duration_s")
        summary_manifest = manifest.to_model_manifest()["datasets"][1]
        self.assertEqual(summary_manifest["dataset_id"], "workout_summary")
        self.assertEqual(summary_manifest["row_count"], 1)
        self.assertNotIn("rows", summary_manifest)

    def test_compile_spec_selects_workout_comparison_dataset_for_comparison_request(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("distance_km",),
            transforms=(),
            comparison=True,
        )
        manifest = resolve_datasets(
            request,
            points=(),
            comparison_workouts=(
                _workout(workout_id="w1", title="Run 1", distance_km=5.0),
                _workout(workout_id="w2", title="Run 2", distance_km=7.0),
            ),
        )

        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(spec.x.dataset_id, "workout_comparison")
        self.assertEqual(spec.x.column_id, "workout_title")
        self.assertEqual(spec.y[0].column_id, "distance_km")
        comparison_manifest = manifest.to_model_manifest()["datasets"][1]
        self.assertEqual(comparison_manifest["dataset_id"], "workout_comparison")
        self.assertEqual(comparison_manifest["row_count"], 2)
        self.assertNotIn("rows", comparison_manifest)

    def test_compile_spec_selects_short_period_label_for_period_dataset(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("ascent_m",),
            transforms=(),
            chart_kind="bar",
        )
        manifest = resolve_datasets(
            request,
            points=(),
            period_workouts=(
                _workout(workout_id="w1", title="Sipoo Running", local_date="2026-06-01", ascent_m=20.0),
                _workout(workout_id="w2", title="Sipoo Running", local_date="2026-06-07", ascent_m=30.0),
                _workout(workout_id="w3", title="Sipoo Running", local_date="2026-06-07", ascent_m=40.0),
            ),
        )

        spec = compile_visualization_spec(request, manifest)
        period = manifest.dataset("workout_period")

        self.assertEqual(spec.mark, "bar")
        self.assertEqual(spec.x.dataset_id, "workout_period")
        self.assertEqual(spec.x.column_id, "workout_label")
        self.assertEqual([row["workout_label"] for row in period.rows], ["1/6", "7/6 #1", "7/6 #2"])
        self.assertEqual([row["workout_title"] for row in period.rows], ["Sipoo Running", "Sipoo Running", "Sipoo Running"])

    def test_route_metric_adds_route_points_dataset_without_model_rows(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="longitude",
            y_metrics=("route",),
            transforms=(),
            chart_kind="map",
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, latitude=60.17, longitude=24.94),
                WorkoutPointRecord(workout_id="w", point_index=1, latitude=60.18, longitude=24.95),
            ),
            workout=_workout(workout_id="w", title="Route workout"),
        )

        route_dataset = manifest.dataset("route_points")
        model_manifest = manifest.to_model_manifest()
        route_model_dataset = next(dataset for dataset in model_manifest["datasets"] if dataset["dataset_id"] == "route_points")

        self.assertIsNotNone(route_dataset)
        self.assertEqual(route_dataset.rows[0]["latitude"], 60.17)
        self.assertEqual(route_dataset.rows[0]["longitude"], 24.94)
        self.assertIn("route", [column["column_id"] for column in route_model_dataset["columns"]])
        self.assertNotIn("rows", route_model_dataset)

    def test_compile_spec_rejects_unknown_metric_and_transform(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("unknown_metric",), transforms=())
        manifest = resolve_datasets(request, points=())

        with self.assertRaises(UnsupportedColumnError):
            compile_visualization_spec(request, manifest)

        bad_transform = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm",),
            transforms=("teleport",),
        )
        manifest = resolve_datasets(
            bad_transform,
            points=(WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),),
        )
        with self.assertRaises(UnsupportedTransformError):
            compile_visualization_spec(bad_transform, manifest)

    def test_compile_spec_rejects_unknown_chart_kind_with_safe_validation_issue(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm",),
            transforms=(),
            chart_kind="scatter",
        )
        manifest = resolve_datasets(
            request,
            points=(WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),),
        )

        with self.assertRaises(UnsupportedMarkError) as caught:
            compile_visualization_spec(request, manifest)

        issue = visualization_validation_issue(caught.exception, manifest).to_model_error()
        self.assertEqual(issue["code"], "unsupported_mark")
        self.assertEqual(issue["path"], "chart_kind")
        self.assertEqual(issue["value"], "scatter")
        self.assertIn("pie", issue["allowed_values"])

    def test_compile_spec_rejects_missing_renderable_metric_data(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("heart_rate_bpm",), transforms=())
        manifest = resolve_datasets(
            request,
            points=(WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0),),
        )

        with self.assertRaises(MissingRenderableDataError):
            compile_visualization_spec(request, manifest)

    def test_model_manifest_contains_stats_not_raw_rows(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("heart_rate_bpm",), transforms=())
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=None),
            ),
        )

        model_manifest = manifest.to_model_manifest()

        dataset = model_manifest["datasets"][0]
        self.assertEqual(dataset["dataset_id"], "workout_points")
        self.assertEqual(dataset["row_count"], 2)
        self.assertNotIn("rows", dataset)
        heart_rate = next(column for column in dataset["columns"] if column["column_id"] == "heart_rate_bpm")
        self.assertEqual(heart_rate["null_count"], 1)
        self.assertEqual(heart_rate["min_value"], 120)
        self.assertEqual(heart_rate["max_value"], 120)
        self.assertIn("filter_non_null", heart_rate["allowed_transforms"])
        self.assertIn("rolling_average", heart_rate["allowed_transforms"])
        self.assertIn("aggregate_avg", heart_rate["allowed_transforms"])
        self.assertIn("aggregate_sum", heart_rate["allowed_transforms"])

    def test_filter_non_null_transform_removes_rows_missing_any_encoding(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm", "pace_s_per_km"),
            transforms=("filter_non_null",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=0,
                    elapsed_s=0,
                    heart_rate_bpm=120,
                    pace_s_per_km=360,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=1,
                    elapsed_s=60,
                    heart_rate_bpm=None,
                    pace_s_per_km=370,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=2,
                    elapsed_s=120,
                    heart_rate_bpm=130,
                    pace_s_per_km=None,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=3,
                    elapsed_s=180,
                    heart_rate_bpm=135,
                    pace_s_per_km=365,
                ),
            ),
        )
        spec = compile_visualization_spec(request, manifest)

        rows = _transformed_rows(spec, manifest.dataset("workout_points"))

        self.assertEqual(tuple(row["elapsed_s"] for row in rows), (0, 180))

    def test_rolling_average_smooths_numeric_series_without_filling_missing_values(self) -> None:
        smoothed = _apply_rolling_average(
            (
                RenderSeries(
                    metric="heart_rate_bpm",
                    values=(10.0, 20.0, None, 80.0),
                ),
            ),
            window_size=3,
        )

        self.assertEqual(smoothed[0].metric, "heart_rate_bpm")
        self.assertEqual(smoothed[0].values, (15.0, 15.0, None, 80.0))
        self.assertTrue(smoothed[0].smoothed)

    def test_explicit_smoothing_window_scales_with_visible_points(self) -> None:
        self.assertEqual(_explicit_smooth_window(tuple(float(index) for index in range(10))), 5)
        self.assertEqual(_explicit_smooth_window(tuple(float(index) for index in range(4268))), 61)

    def test_normalization_uses_robust_domain_for_scaled_outlier_series(self) -> None:
        normalized = _apply_normalization(
            (
                RenderSeries(metric="primary", values=(100.0, 110.0, 120.0, 130.0, 140.0)),
                RenderSeries(metric="secondary", values=(10.0, 11.0, 10.5, 11.5, 10.8, 11.2, 10.9, 11.1, 10.7, 500.0)),
            )
        )

        self.assertFalse(normalized[0].scaled)
        self.assertTrue(normalized[1].scaled)
        self.assertTrue(normalized[1].clipped)
        self.assertGreater(max(value for value in normalized[1].values if value is not None), 130)
        self.assertLess(min(value for value in normalized[1].values if value is not None), 110)

    def test_chart_text_uses_workout_title_for_single_workout_and_localized_subject_for_period(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm", "pace_s_per_km"),
            transforms=(),
        )
        spec = compile_visualization_spec(
            request,
            resolve_datasets(
                request,
                points=(
                    WorkoutPointRecord(
                        workout_id="w",
                        point_index=0,
                        elapsed_s=0,
                        heart_rate_bpm=120,
                        pace_s_per_km=360,
                    ),
                ),
            ),
        )
        workout = _workout(title="Morning run")
        period = _workout(title="Kaikki treenit", kind="period", primary_kind="period", local_date="2026-06-01..2026-06-17")

        self.assertEqual(_chart_title(workout, spec, language=SupportedLanguage.FI), "Morning run")
        self.assertEqual(_chart_title(period, spec, language=SupportedLanguage.FI), "Mittarit")
        self.assertEqual(_chart_title(period, spec, language=SupportedLanguage.EN), "Metrics")

    def test_period_chart_subtitle_uses_localized_route_style_summary(self) -> None:
        period = _workout(
            title="Kaikki treenit",
            kind="period",
            primary_kind="period",
            local_date="2026-06-01..2026-06-17",
            distance_km=66.7,
            duration_s=33214,
            avg_hr_bpm=119,
        )

        self.assertEqual(_chart_subtitle(period, language=SupportedLanguage.FI), "1/6/2026 - 17/6/2026 - 66.7 km - 9h 13min 34s - Keskisyke 119")

    def test_chart_labels_are_localized(self) -> None:
        spec = VisualizationSpec(
            mark="pie",
            x=Encoding(dataset_id="heart_rate_zones", column_id="zone_label"),
            y=(Encoding(dataset_id="heart_rate_zones", column_id="heart_rate_zone_seconds"),),
            transforms=("as_percentage_of_total",),
        )

        self.assertEqual(_metric_label("zone_label", language=SupportedLanguage.FI), "Sykealue")
        self.assertEqual(_metric_label("heart_rate_bpm", language=SupportedLanguage.EN), "Heart rate")
        self.assertEqual(_y_axis_label(spec, language=SupportedLanguage.FI), "Osuus (%)")

    def test_auto_layout_uses_small_multiples_for_different_units(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm", "pace_s_per_km", "elevation_m"),
            transforms=(),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=0,
                    elapsed_s=0,
                    heart_rate_bpm=120,
                    pace_s_per_km=360,
                    elevation_m=50,
                ),
            ),
        )
        spec = compile_visualization_spec(request, manifest)

        self.assertEqual(_effective_layout_mode("auto", spec), "small_multiples")

    def test_auto_layout_keeps_same_unit_series_on_single_axis(self) -> None:
        spec = VisualizationSpec(
            mark="line",
            x=Encoding(dataset_id="workout_points", column_id="elapsed_s"),
            y=(
                Encoding(dataset_id="workout_points", column_id="heart_rate_bpm"),
                Encoding(dataset_id="workout_points", column_id="avg_hr_bpm"),
                Encoding(dataset_id="workout_points", column_id="max_hr_bpm"),
            ),
        )

        self.assertEqual(_effective_layout_mode("auto", spec), "single_axis")

    def test_aggregate_transform_builds_metric_bars(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_bpm", "pace_s_per_km"),
            transforms=("aggregate_avg",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=0,
                    elapsed_s=0,
                    heart_rate_bpm=120,
                    pace_s_per_km=360,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=1,
                    elapsed_s=60,
                    heart_rate_bpm=140,
                    pace_s_per_km=None,
                ),
            ),
        )
        spec = compile_visualization_spec(request, manifest)

        bars = _aggregate_bars(spec, manifest.dataset("workout_points").rows)

        self.assertEqual(tuple(bar.label for bar in bars), ("heart_rate_bpm", "pace_s_per_km"))
        self.assertEqual(tuple(bar.value for bar in bars), (130.0, 360.0))

    def test_aggregate_transform_does_not_collapse_nominal_bar_distribution(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="elapsed_s",
            y_metrics=("heart_rate_zone_seconds",),
            transforms=("aggregate_sum",),
        )
        manifest = resolve_datasets(
            request,
            points=(
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=120),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
                WorkoutPointRecord(workout_id="w", point_index=2, elapsed_s=120, heart_rate_bpm=150),
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="pk1", upper_bpm=124),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="pk2", lower_bpm=125, upper_bpm=144),
                HeartRateZoneRecord(user_id="u", zone_key="z3", label="vk1", lower_bpm=145),
            ),
        )
        spec = compile_visualization_spec(request, manifest)
        dataset = manifest.dataset("hr_zone_distribution")

        self.assertIsNotNone(dataset)
        assert dataset is not None
        self.assertFalse(_should_render_metric_aggregate_bars(spec, dataset))
        self.assertEqual(tuple(row["zone_label"] for row in dataset.rows), ("pk1", "pk2", "vk1"))

    def test_pie_chart_renderer_outputs_png_for_generic_slices(self) -> None:
        content = PillowVisualizationRenderer().render_pie_chart_png(
            PieChart(
                title="Generic distribution",
                slices=(
                    PieSlice(label="A", value=2),
                    PieSlice(label="B", value=3),
                    PieSlice(label="C", value=5),
                ),
                value_label="Value",
            )
        )

        self.assertTrue(content.startswith(b"\x89PNG"))
        self.assertGreater(len(content), 1000)

    def test_pie_chart_renderer_accepts_zero_value_legend_items(self) -> None:
        content = PillowVisualizationRenderer().render_pie_chart_png(
            PieChart(
                title="Generic distribution",
                slices=(
                    PieSlice(label="A", value=2),
                    PieSlice(label="B", value=0),
                    PieSlice(label="C", value=3),
                ),
                value_label="Share of total (%)",
                value_format="percentage",
            )
        )

        self.assertTrue(content.startswith(b"\x89PNG"))
        self.assertGreater(len(content), 1000)

    def test_named_and_hex_color_hints_are_metadata_driven(self) -> None:
        self.assertEqual(_color_hint("green"), (22, 163, 74))
        self.assertEqual(_color_hint("#123abc"), (18, 58, 188))
        self.assertIsNone(_color_hint("not-a-color"))

    def test_render_workout_summary_metric_without_point_rows(self) -> None:
        artifact = render_workout_visualization(
            _workout(duration_s=3600, distance_km=10.0),
            (),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="elapsed_s",
                y_metrics=("duration_s",),
                transforms=(),
                date_range={},
                comparison_mode="",
            ),
        )

        self.assertEqual(artifact.content_type, "image/png")
        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("duration_s",))

    def test_render_multi_unit_line_metrics_as_small_multiples_by_default(self) -> None:
        artifact = render_workout_visualization(
            _workout(duration_s=120, distance_km=0.5),
            (
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=0,
                    elapsed_s=0,
                    heart_rate_bpm=100,
                    pace_s_per_km=360,
                    elevation_m=42,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=1,
                    elapsed_s=60,
                    heart_rate_bpm=120,
                    pace_s_per_km=370,
                    elevation_m=46,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=2,
                    elapsed_s=120,
                    heart_rate_bpm=130,
                    pace_s_per_km=365,
                    elevation_m=44,
                ),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="elapsed_s",
                y_metrics=("heart_rate_bpm", "pace_s_per_km", "elevation_m"),
                transforms=(),
                date_range={},
                comparison_mode="",
                layout_mode="auto",
            ),
        )

        self.assertEqual(artifact.content_type, "image/png")
        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("heart_rate_bpm", "pace_s_per_km", "elevation_m"))
        self.assertEqual(artifact.scaled_metrics, ())

    def test_render_explicit_single_axis_scales_different_units(self) -> None:
        artifact = render_workout_visualization(
            _workout(duration_s=60, distance_km=0.2),
            (
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=0,
                    elapsed_s=0,
                    heart_rate_bpm=100,
                    pace_s_per_km=360,
                ),
                WorkoutPointRecord(
                    workout_id="w",
                    point_index=1,
                    elapsed_s=60,
                    heart_rate_bpm=120,
                    pace_s_per_km=370,
                ),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="elapsed_s",
                y_metrics=("heart_rate_bpm", "pace_s_per_km"),
                transforms=(),
                date_range={},
                comparison_mode="",
                layout_mode="single_axis",
            ),
        )

        self.assertEqual(artifact.scaled_metrics, ("pace_s_per_km",))

    def test_render_workout_comparison_metric_without_point_rows(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w1", title="Run 1", distance_km=5.0),
            (),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="elapsed_s",
                y_metrics=("distance_km",),
                transforms=(),
                date_range={},
                comparison_mode="recent",
            ),
            comparison_workouts=(
                _workout(workout_id="w1", title="Run 1", distance_km=5.0),
                _workout(workout_id="w2", title="Run 2", distance_km=7.0),
            ),
        )

        self.assertEqual(artifact.content_type, "image/png")
        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("distance_km",))

    def test_render_explicit_pie_chart_for_categorical_numeric_dataset(self) -> None:
        artifact = render_workout_visualization(
            _workout(duration_s=120, distance_km=0.5),
            (
                WorkoutPointRecord(workout_id="w", point_index=0, elapsed_s=0, heart_rate_bpm=100),
                WorkoutPointRecord(workout_id="w", point_index=1, elapsed_s=60, heart_rate_bpm=130),
                WorkoutPointRecord(workout_id="w", point_index=2, elapsed_s=120, heart_rate_bpm=150),
            ),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="heart_rate_zone_seconds",
                y_metrics=("heart_rate_zone_seconds",),
                transforms=("as_percentage_of_total",),
                date_range={},
                comparison_mode="",
                chart_kind="pie",
            ),
            heart_rate_zones=(
                HeartRateZoneRecord(user_id="u", zone_key="z1", label="Easy", upper_bpm=119),
                HeartRateZoneRecord(user_id="u", zone_key="z2", label="Steady", lower_bpm=120, upper_bpm=139),
                HeartRateZoneRecord(user_id="u", zone_key="z3", label="Hard", lower_bpm=140),
            ),
        )

        self.assertEqual(artifact.content_type, "image/png")
        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("heart_rate_zone_seconds",))

    def test_render_explicit_pie_chart_for_comparison_metric_dataset(self) -> None:
        artifact = render_workout_visualization(
            _workout(workout_id="w1", title="Run 1", distance_km=5.0),
            (),
            VisualizationIntent(
                workout_selector={"type": "latest"},
                x_metric="workout_title",
                y_metrics=("distance_km",),
                transforms=(),
                date_range={},
                comparison_mode="recent",
                chart_kind="pie",
            ),
            comparison_workouts=(
                _workout(workout_id="w1", title="Run 1", distance_km=5.0),
                _workout(workout_id="w2", title="Run 2", distance_km=7.0),
                _workout(workout_id="w3", title="Run 3", distance_km=8.0),
            ),
        )

        self.assertEqual(artifact.content_type, "image/png")
        self.assertTrue(artifact.content.startswith(b"\x89PNG"))
        self.assertEqual(artifact.rendered_metrics, ("distance_km",))


def _workout(**overrides) -> WorkoutRecord:
    values = {
        "workout_id": "w",
        "owner_user_id": "u",
        "source_attachment_id": None,
        "guild_id": None,
        "channel_id": None,
        "title": "Test workout",
        "kind": "activity",
        "primary_kind": "activity",
        "start_time_utc": None,
        "start_time_local": None,
        "local_date": None,
        "distance_km": None,
        "duration_s": None,
        "pace_s_per_km": None,
        "ascent_m": None,
        "avg_hr_bpm": None,
        "max_hr_bpm": None,
        "point_count": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return WorkoutRecord(**values)


def _solid_png(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


if __name__ == "__main__":
    unittest.main()
