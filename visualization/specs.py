from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from visualization.datasets import DatasetManifest, DatasetRequest


SUPPORTED_MARKS = {"line", "bar", "pie"}
SUPPORTED_CHART_KINDS = SUPPORTED_MARKS | {"auto", "map"}
SUPPORTED_TRANSFORMS = {
    "normalize_to_primary_range",
    "filter_non_null",
    "smooth",
    "rolling_average",
    "aggregate_sum",
    "aggregate_avg",
    "as_percentage_of_total",
}


@dataclass(frozen=True)
class Encoding:
    dataset_id: str
    column_id: str


@dataclass(frozen=True)
class VisualizationSpec:
    mark: str
    x: Encoding
    y: tuple[Encoding, ...]
    transforms: tuple[str, ...] = ()
    output_filename_suffix: str = "chart"


@dataclass(frozen=True)
class VisualizationValidationIssue:
    code: str
    path: str
    value: object = ""
    allowed_values: tuple[str, ...] = ()

    def to_model_error(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "value": self.value,
            "allowed_values": list(self.allowed_values),
        }


class VisualizationSpecError(ValueError):
    pass


class UnsupportedMarkError(VisualizationSpecError):
    def __init__(self, mark: str) -> None:
        self.mark = mark
        super().__init__(mark)


class UnsupportedColumnError(VisualizationSpecError):
    def __init__(self, column_id: str) -> None:
        self.column_id = column_id
        super().__init__(column_id)


class UnsupportedTransformError(VisualizationSpecError):
    def __init__(self, transform: str) -> None:
        self.transform = transform
        super().__init__(transform)


class EmptyEncodingError(VisualizationSpecError):
    pass


class TransformNotApplicableError(VisualizationSpecError):
    def __init__(self, transform: str) -> None:
        self.transform = transform
        super().__init__(transform)


class MissingRenderableDataError(VisualizationSpecError):
    def __init__(self, column_id: str) -> None:
        self.column_id = column_id
        super().__init__(column_id)


def compile_visualization_spec(request: DatasetRequest, manifest: DatasetManifest) -> VisualizationSpec:
    _validate_request_primitives(request)
    dataset = _select_dataset(request, manifest)
    x_column = _select_x_column(request, dataset)
    mark = _select_mark(request, dataset, x_column)
    spec = VisualizationSpec(
        mark=mark,
        x=Encoding(dataset_id=dataset.dataset_id, column_id=x_column.column_id),
        y=tuple(Encoding(dataset_id=dataset.dataset_id, column_id=metric) for metric in request.metrics),
        transforms=request.transforms,
        output_filename_suffix=dataset.dataset_id.replace("_", "-"),
    )
    validate_visualization_spec(spec, manifest)
    return spec


def validate_visualization_spec(spec: VisualizationSpec, manifest: DatasetManifest) -> None:
    if spec.mark not in SUPPORTED_MARKS:
        raise UnsupportedMarkError(spec.mark)
    if not spec.y:
        raise EmptyEncodingError("Visualization spec requires at least one y encoding")
    for transform in spec.transforms:
        if transform not in SUPPORTED_TRANSFORMS:
            raise UnsupportedTransformError(transform)
    _validate_encoding(spec.x, manifest, require_values=spec.mark == "line")
    for encoding in spec.y:
        _validate_encoding(encoding, manifest, require_values=True)
    if "as_percentage_of_total" in spec.transforms:
        _validate_percentage_transform(spec, manifest)
    if spec.mark == "pie":
        _validate_pie_spec(spec, manifest)


def _validate_encoding(encoding: Encoding, manifest: DatasetManifest, *, require_values: bool) -> None:
    dataset = manifest.dataset(encoding.dataset_id)
    if dataset is None:
        raise UnsupportedColumnError(f"{encoding.dataset_id}.{encoding.column_id}")
    column = next((candidate for candidate in dataset.columns if candidate.column_id == encoding.column_id), None)
    if column is None:
        raise UnsupportedColumnError(encoding.column_id)
    if require_values and (not dataset.rows or column.null_count >= len(dataset.rows)):
        raise MissingRenderableDataError(encoding.column_id)


def _select_dataset(request: DatasetRequest, manifest: DatasetManifest):
    requested = set(request.metrics)
    if request.comparison:
        comparison = manifest.dataset("workout_comparison")
        if comparison is not None:
            columns = {column.column_id for column in comparison.columns}
            if requested and requested.issubset(columns):
                return comparison
    for dataset in manifest.datasets:
        columns = {column.column_id for column in dataset.columns}
        if requested and requested.issubset(columns):
            return dataset
    missing = request.metrics[0] if request.metrics else ""
    raise UnsupportedColumnError(missing)


def _select_x_column(request: DatasetRequest, dataset):
    for column in dataset.columns:
        if column.semantic_type in {"temporal", "ordinal", "nominal"} and column.column_id not in request.metrics:
            return column
    for column in dataset.columns:
        if column.column_id == request.x_metric:
            return column
    raise UnsupportedColumnError(request.x_metric)


def _select_mark(request: DatasetRequest, dataset, x_column) -> str:
    del dataset
    if request.chart_kind == "pie":
        return "pie"
    if request.chart_kind == "bar":
        return "bar"
    if request.chart_kind == "line":
        return "line"
    if x_column.semantic_type == "nominal":
        return "bar"
    return "line"


def _validate_percentage_transform(spec: VisualizationSpec, manifest: DatasetManifest) -> None:
    if spec.mark not in {"bar", "pie"} or len(spec.y) != 1:
        raise TransformNotApplicableError("as_percentage_of_total")
    dataset = manifest.dataset(spec.x.dataset_id)
    if dataset is None:
        raise UnsupportedColumnError(spec.x.dataset_id)
    x_column = next((column for column in dataset.columns if column.column_id == spec.x.column_id), None)
    y_column = next((column for column in dataset.columns if column.column_id == spec.y[0].column_id), None)
    if x_column is None or y_column is None:
        raise UnsupportedColumnError(spec.y[0].column_id)
    if x_column.semantic_type not in {"nominal", "ordinal"} or y_column.semantic_type != "quantitative":
        raise TransformNotApplicableError("as_percentage_of_total")


def _validate_pie_spec(spec: VisualizationSpec, manifest: DatasetManifest) -> None:
    if len(spec.y) != 1:
        raise TransformNotApplicableError("pie")
    dataset = manifest.dataset(spec.x.dataset_id)
    if dataset is None:
        raise UnsupportedColumnError(spec.x.dataset_id)
    x_column = next((column for column in dataset.columns if column.column_id == spec.x.column_id), None)
    y_column = next((column for column in dataset.columns if column.column_id == spec.y[0].column_id), None)
    if x_column is None or y_column is None:
        raise UnsupportedColumnError(spec.y[0].column_id)
    if x_column.semantic_type not in {"nominal", "ordinal"} or y_column.semantic_type != "quantitative":
        raise TransformNotApplicableError("pie")


def visualization_validation_issue(
    exc: VisualizationSpecError,
    manifest: DatasetManifest,
) -> VisualizationValidationIssue:
    if isinstance(exc, UnsupportedMarkError):
        return VisualizationValidationIssue(
            code="unsupported_mark",
            path="chart_kind",
            value=exc.mark,
            allowed_values=tuple(sorted(SUPPORTED_CHART_KINDS)),
        )
    if isinstance(exc, UnsupportedTransformError):
        return VisualizationValidationIssue(
            code="unsupported_transform",
            path="transforms",
            value=exc.transform,
            allowed_values=tuple(sorted(SUPPORTED_TRANSFORMS)),
        )
    if isinstance(exc, UnsupportedColumnError):
        return VisualizationValidationIssue(
            code="unsupported_column",
            path="metric_or_encoding",
            value=exc.column_id,
            allowed_values=tuple(sorted(_manifest_columns(manifest))),
        )
    if isinstance(exc, MissingRenderableDataError):
        return VisualizationValidationIssue(
            code="missing_renderable_data",
            path="encodings.y",
            value=exc.column_id,
            allowed_values=tuple(sorted(_manifest_columns_with_values(manifest))),
        )
    if isinstance(exc, TransformNotApplicableError):
        return VisualizationValidationIssue(
            code="transform_not_applicable",
            path="transforms",
            value=exc.transform,
            allowed_values=tuple(sorted(SUPPORTED_TRANSFORMS)),
        )
    if isinstance(exc, EmptyEncodingError):
        return VisualizationValidationIssue(
            code="empty_y_encoding",
            path="requested_metrics",
            value="",
            allowed_values=tuple(sorted(_manifest_columns_with_values(manifest))),
        )
    return VisualizationValidationIssue(code=type(exc).__name__, path="visualization_spec", value=str(exc))


def allowed_visualization_primitives() -> dict[str, Any]:
    return {
        "chart_kinds": list(sorted(SUPPORTED_CHART_KINDS)),
        "marks": list(sorted(SUPPORTED_MARKS)),
        "output_modes": ["chart", "social_image"],
        "transforms": list(sorted(SUPPORTED_TRANSFORMS)),
    }


def _validate_request_primitives(request: DatasetRequest) -> None:
    if request.chart_kind not in SUPPORTED_CHART_KINDS:
        raise UnsupportedMarkError(request.chart_kind)


def _manifest_columns(manifest: DatasetManifest) -> set[str]:
    return {column.column_id for dataset in manifest.datasets for column in dataset.columns}


def _manifest_columns_with_values(manifest: DatasetManifest) -> set[str]:
    values: set[str] = set()
    for dataset in manifest.datasets:
        for column in dataset.columns:
            if dataset.rows and column.null_count < len(dataset.rows):
                values.add(column.column_id)
    return values
