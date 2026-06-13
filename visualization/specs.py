from __future__ import annotations

from dataclasses import dataclass

from visualization.datasets import DatasetManifest, DatasetRequest


SUPPORTED_MARKS = {"line", "bar"}
SUPPORTED_TRANSFORMS = {"normalize_to_primary_range", "filter_non_null"}


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


class MissingRenderableDataError(VisualizationSpecError):
    def __init__(self, column_id: str) -> None:
        self.column_id = column_id
        super().__init__(column_id)


def compile_visualization_spec(request: DatasetRequest, manifest: DatasetManifest) -> VisualizationSpec:
    dataset = _select_dataset(request, manifest)
    x_column = _select_x_column(request, dataset)
    mark = _select_mark(dataset, x_column)
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
    for dataset in manifest.datasets:
        columns = {column.column_id for column in dataset.columns}
        if requested and requested.issubset(columns):
            return dataset
    missing = request.metrics[0] if request.metrics else ""
    raise UnsupportedColumnError(missing)


def _select_x_column(request: DatasetRequest, dataset):
    for column in dataset.columns:
        if column.column_id == request.x_metric:
            return column
    for column in dataset.columns:
        if column.semantic_type in {"temporal", "ordinal", "nominal"}:
            return column
    raise UnsupportedColumnError(request.x_metric)


def _select_mark(dataset, x_column) -> str:
    del dataset
    if x_column.semantic_type == "nominal":
        return "bar"
    return "line"
