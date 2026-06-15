from __future__ import annotations

import unittest

from llm.operations import VisualizationIntent
from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord, WorkoutRecord
from visualization.datasets import dataset_request_from_metrics, resolve_datasets
from visualization.metrics import infer_transforms_from_text
from visualization.render import (
    MARKER_POINT_LIMIT,
    Axis,
    RenderSeries,
    _background,
    _show_markers,
    _axis,
    _format_tick,
    _fill_short_gaps,
    _prepare_render_series,
    _robust_axis,
    _scale_y,
    _time_axis,
)
from visualization.specs import (
    Encoding,
    MissingRenderableDataError,
    UnsupportedColumnError,
    UnsupportedTransformError,
    VisualizationSpec,
    compile_visualization_spec,
)
from visualization.service import (
    _aggregate_bars,
    _apply_rolling_average,
    _effective_layout_mode,
    _explicit_smooth_window,
    _invert_y_axis,
    _should_render_metric_aggregate_bars,
    _transformed_rows,
    render_workout_visualization,
)
from visualization.service import _apply_normalization, _chart_title


class VisualizationSpecTests(unittest.TestCase):
    def test_background_uses_subtle_vertical_gradient(self) -> None:
        pixels = _background(1, 3)

        self.assertNotEqual(bytes(pixels[0:3]), bytes(pixels[-3:]))
        self.assertGreaterEqual(min(pixels), 244)

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

    def test_short_internal_gaps_are_filled_for_smoothed_rendering(self) -> None:
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

    def test_dataset_request_canonicalizes_metric_aliases(self) -> None:
        request = dataset_request_from_metrics(
            x_metric="aika",
            y_metrics=("syke", "vauhti"),
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

    def test_compile_spec_selects_workout_summary_dataset_for_summary_metric(self) -> None:
        request = dataset_request_from_metrics(x_metric="elapsed_s", y_metrics=("duration",), transforms=())
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

    def test_infer_transforms_detects_normalize_and_smoothing(self) -> None:
        transforms = infer_transforms_from_text("piirra syke tasoitettuna ja vauhti skaalattuna samaan kuvaajaan")

        self.assertEqual(transforms, ("normalize_to_primary_range", "rolling_average"))

    def test_infer_transforms_detects_aggregation(self) -> None:
        self.assertEqual(infer_transforms_from_text("näytä sykkeen keskiarvo"), ("aggregate_avg",))
        self.assertEqual(infer_transforms_from_text("näytä nousu yhteensä"), ("aggregate_sum",))

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

    def test_multi_series_title_is_generic(self) -> None:
        spec = compile_visualization_spec(
            dataset_request_from_metrics(
                x_metric="elapsed_s",
                y_metrics=("heart_rate_bpm", "pace_s_per_km"),
                transforms=(),
            ),
            resolve_datasets(
                dataset_request_from_metrics(
                    x_metric="elapsed_s",
                    y_metrics=("heart_rate_bpm", "pace_s_per_km"),
                    transforms=(),
                ),
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

        self.assertEqual(_chart_title("Morning run", spec), "Workout metrics - Morning run")

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


if __name__ == "__main__":
    unittest.main()
