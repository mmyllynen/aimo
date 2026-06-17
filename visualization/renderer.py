from __future__ import annotations

from typing import Literal, Protocol

from core.config import RenderersConfig
from visualization.render import BarChart, LineChart, MultiPanelLineChart, PieChart, RouteMap


ChartType = Literal["line", "multi_panel_line", "bar", "pie", "route"]
RendererName = Literal["internal", "pillow"]


class RendererUnavailableError(RuntimeError):
    pass


class VisualizationRenderer(Protocol):
    name: str

    def render_line_chart_png(self, chart: LineChart) -> bytes: ...

    def render_multi_panel_line_chart_png(self, chart: MultiPanelLineChart) -> bytes: ...

    def render_bar_chart_png(self, chart: BarChart) -> bytes: ...

    def render_pie_chart_png(self, chart: PieChart) -> bytes: ...

    def render_route_map_png(self, chart: RouteMap) -> bytes: ...


def renderer_name(config: RenderersConfig | None, chart_type: ChartType) -> RendererName:
    config = config or RenderersConfig()
    value = getattr(config, chart_type) or config.default
    return value  # type: ignore[return-value]


def resolve_renderer(config: RenderersConfig | None, chart_type: ChartType) -> VisualizationRenderer:
    name = renderer_name(config, chart_type)
    if name == "internal":
        from visualization.internal_renderer import InternalVisualizationRenderer

        return InternalVisualizationRenderer()
    if name == "pillow":
        try:
            from visualization.pillow_renderer import PillowVisualizationRenderer
        except ImportError as exc:
            raise RendererUnavailableError("Pillow renderer requested but Pillow is not installed") from exc
        return PillowVisualizationRenderer()
    raise RendererUnavailableError(f"Unknown renderer {name!r}")
