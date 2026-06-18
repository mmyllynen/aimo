from __future__ import annotations

from typing import Literal, Protocol

from visualization.render import BarChart, LineChart, MultiPanelLineChart, PieChart, RouteMap, SocialImage


ChartType = Literal["line", "multi_panel_line", "bar", "pie", "route", "social_image"]


class RendererUnavailableError(RuntimeError):
    pass


class VisualizationRenderer(Protocol):
    name: str

    def render_line_chart_png(self, chart: LineChart) -> bytes: ...

    def render_multi_panel_line_chart_png(self, chart: MultiPanelLineChart) -> bytes: ...

    def render_bar_chart_png(self, chart: BarChart) -> bytes: ...

    def render_pie_chart_png(self, chart: PieChart) -> bytes: ...

    def render_route_map_png(self, chart: RouteMap) -> bytes: ...

    def render_social_image_png(self, chart: SocialImage) -> bytes: ...


def resolve_renderer(chart_type: ChartType) -> VisualizationRenderer:
    try:
        from visualization.pillow_renderer import PillowVisualizationRenderer
    except ImportError as exc:
        raise RendererUnavailableError("Pillow renderer is required but Pillow is not installed") from exc
    return PillowVisualizationRenderer()
