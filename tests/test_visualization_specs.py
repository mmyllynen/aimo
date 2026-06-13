from __future__ import annotations

import unittest

from storage.repositories import HeartRateZoneRecord, WorkoutPointRecord
from visualization.datasets import dataset_request_from_metrics, resolve_datasets
from visualization.specs import (
    MissingRenderableDataError,
    UnsupportedColumnError,
    UnsupportedTransformError,
    compile_visualization_spec,
)


class VisualizationSpecTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
