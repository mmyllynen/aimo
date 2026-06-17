from __future__ import annotations

from visualization.render import (
    BarChart,
    LineChart,
    MultiPanelLineChart,
    PieChart,
    RouteMap,
    SocialImage,
    render_bar_chart_png,
    render_line_chart_png,
    render_multi_panel_line_chart_png,
    render_pie_chart_png,
    render_route_map_png,
)


class InternalVisualizationRenderer:
    name = "internal"

    def render_line_chart_png(self, chart: LineChart) -> bytes:
        return render_line_chart_png(chart)

    def render_multi_panel_line_chart_png(self, chart: MultiPanelLineChart) -> bytes:
        return render_multi_panel_line_chart_png(chart)

    def render_bar_chart_png(self, chart: BarChart) -> bytes:
        return render_bar_chart_png(chart)

    def render_pie_chart_png(self, chart: PieChart) -> bytes:
        return render_pie_chart_png(chart)

    def render_route_map_png(self, chart: RouteMap) -> bytes:
        return render_route_map_png(chart)

    def render_social_image_png(self, chart: SocialImage) -> bytes:
        raise NotImplementedError("social_image rendering requires the Pillow renderer")
