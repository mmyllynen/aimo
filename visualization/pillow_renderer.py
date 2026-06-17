from __future__ import annotations

import math
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from visualization.render import (
    COLORS,
    GRID,
    MUTED_TEXT,
    SIDEBAR_BG,
    SIDEBAR_BORDER,
    TEXT,
    BarChart,
    ChartFrame,
    LegendItem,
    LineChart,
    LinePanel,
    MultiPanelLineChart,
    PieChart,
    RouteMap,
    RoutePolyline,
    _axis,
    _chart_frame,
    _clean_float,
    _ellipsize,
    _format_tick,
    _label_with_suffixes,
    _line_legend_items,
    _mercator_xy,
    _pie_radius,
    _prepare_render_series,
    _robust_axis,
    _scale,
    _scale_y,
    _show_markers,
    _time_axis,
    route_metric_color,
)


RENDER_SCALE = 2


@dataclass(frozen=True)
class ChartOverlayLayout:
    plot_left: int
    plot_top: int
    plot_right: int
    plot_bottom: int
    title_box: tuple[int, int, int, int]
    title_text_width: int
    title_lines: tuple[str, ...]
    subtitle_lines: tuple[str, ...]
    legend_box: tuple[int, int, int, int] | None
    visible_legend_count: int


class PillowVisualizationRenderer:
    name = "pillow"

    def render_line_chart_png(self, chart: LineChart) -> bytes:
        scale = RENDER_SCALE
        image = _background_image(chart.width * scale, chart.height * scale)
        draw = ImageDraw.Draw(image, "RGBA")
        x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
        y_values = tuple(value for series in chart.series for value in series.values)
        preliminary_y_axis = _robust_axis(y_values, target_ticks=6)
        render_series = tuple(_prepare_render_series(series, preliminary_y_axis) for series in chart.series)
        render_y_values = tuple(value for series in render_series for value in series.values)
        y_axis = _robust_axis(render_y_values, target_ticks=6)
        y_label = chart.y_label
        if len(render_series) == 1:
            y_label = _label_with_suffixes(y_label, render_series[0])
        legend_items = _line_legend_items(render_series)
        layout = _chart_overlay_layout(draw, image.width, image.height, chart.title, chart.subtitle, legend_items, scale=scale)
        left, top, right, bottom = layout.plot_left, layout.plot_top, layout.plot_right, layout.plot_bottom
        _draw_axes(
            draw,
            left,
            top,
            right,
            bottom,
            x_axis,
            y_axis,
            chart.x_label,
            y_label,
            x_tick_format=chart.x_tick_format,
            y_tick_format=chart.y_tick_format,
            invert_y=chart.invert_y,
            scale=scale,
        )
        for index, series in enumerate(render_series):
            _draw_series(
                draw,
                chart.x_values,
                series.values,
                x_axis=x_axis,
                y_axis=y_axis,
                left=left,
                right=right,
                top=top,
                bottom=bottom,
                color=COLORS[index % len(COLORS)],
                invert_y=chart.invert_y,
                scale=scale,
            )
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_chart_overlays(image, layout, chart.title, chart.subtitle, legend_items, chart.legend_title, scale=scale)
        return _png_bytes(_downsample(image, chart.width, chart.height))

    def render_multi_panel_line_chart_png(self, chart: MultiPanelLineChart) -> bytes:
        scale = RENDER_SCALE
        image = _background_image(chart.width * scale, chart.height * scale)
        draw = ImageDraw.Draw(image, "RGBA")
        if not chart.panels:
            layout = _chart_overlay_layout(draw, image.width, image.height, chart.title, chart.subtitle, (), scale=scale)
            _draw_image_frame(draw, image.width, image.height, scale=scale)
            _draw_chart_overlays(image, layout, chart.title, chart.subtitle, (), chart.legend_title, scale=scale)
            return _png_bytes(_downsample(image, chart.width, chart.height))
        x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
        prepared_panels = []
        gap = 26 * scale
        legend_items: list[LegendItem] = []
        for index, panel in enumerate(chart.panels):
            preliminary_y_axis = _robust_axis(panel.series.values, target_ticks=5)
            render_series = _prepare_render_series(panel.series, preliminary_y_axis)
            y_axis = _robust_axis(render_series.values, target_ticks=5)
            label = _label_with_suffixes(panel.y_label, render_series)
            color = COLORS[index % len(COLORS)]
            prepared_panels.append((panel, render_series, y_axis, label, color))
            legend_items.append(LegendItem(label=render_series.label or render_series.metric, color=color, note=", ".join(note for note in ("scaled" if render_series.scaled else "", "clipped" if render_series.clipped else "", "smoothed" if render_series.smoothed else "") if note), line=True))
        layout = _chart_overlay_layout(draw, image.width, image.height, chart.title, chart.subtitle, tuple(legend_items), scale=scale)
        left, top, right, bottom = layout.plot_left, layout.plot_top, layout.plot_right, layout.plot_bottom
        panel_count = len(prepared_panels)
        panel_height = max(72 * scale, (bottom - top - gap * (panel_count - 1)) // panel_count)
        for index, (panel, render_series, y_axis, label, color) in enumerate(prepared_panels):
            panel_top = top + index * (panel_height + gap)
            panel_bottom = panel_top + panel_height
            _draw_axes(
                draw,
                left,
                panel_top,
                right,
                panel_bottom,
                x_axis,
                y_axis,
                chart.x_label if index == panel_count - 1 else "",
                label,
                x_tick_format=chart.x_tick_format,
                y_tick_format=panel.y_tick_format,
                invert_y=panel.invert_y,
                scale=scale,
                draw_x_text=index == panel_count - 1,
            )
            _draw_series(
                draw,
                chart.x_values,
                render_series.values,
                x_axis=x_axis,
                y_axis=y_axis,
                left=left,
                right=right,
                top=panel_top,
                bottom=panel_bottom,
                color=color,
                invert_y=panel.invert_y,
                scale=scale,
            )
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_chart_overlays(image, layout, chart.title, chart.subtitle, tuple(legend_items), chart.legend_title, scale=scale)
        return _png_bytes(_downsample(image, chart.width, chart.height))

    def render_bar_chart_png(self, chart: BarChart) -> bytes:
        scale = RENDER_SCALE
        image = _background_image(chart.width * scale, chart.height * scale)
        draw = ImageDraw.Draw(image, "RGBA")
        legend_items = tuple(
            LegendItem(label=bar.label, color=bar.color or COLORS[index % len(COLORS)], value=bar.value, value_format=chart.y_tick_format)
            for index, bar in enumerate(chart.bars)
        )
        layout = _chart_overlay_layout(draw, image.width, image.height, chart.title, chart.subtitle, legend_items, scale=scale)
        left, top, right, bottom = layout.plot_left, layout.plot_top, layout.plot_right, layout.plot_bottom
        values = tuple(bar.value for bar in chart.bars)
        y_axis = _axis(values, target_ticks=6, include_zero=True)
        _draw_y_axis(draw, left, top, right, bottom, y_axis, chart.y_label, chart.y_tick_format, scale=scale)
        _draw_text_center(draw, (left + right) // 2, bottom + 42 * scale, chart.x_label, MUTED_TEXT, _font(12 * scale))
        if chart.bars:
            gap = max(6 * scale, (right - left) // max(len(chart.bars) * 6, 1))
            slot_width = max(1, (right - left - gap * (len(chart.bars) + 1)) / len(chart.bars))
            zero_y = _scale_y(0.0, y_axis.domain, bottom, top, invert=False)
            for index, bar in enumerate(chart.bars):
                color = bar.color or COLORS[index % len(COLORS)]
                x1 = round(left + gap + index * (slot_width + gap))
                x2 = round(x1 + slot_width)
                y = _scale_y(bar.value, y_axis.domain, bottom, top, invert=False)
                draw.rectangle((x1, min(y, zero_y), x2, max(y, zero_y)), fill=color)
                _draw_text_center(draw, (x1 + x2) // 2, bottom + 12 * scale, _ellipsize(bar.label, max(3, int(slot_width // (6 * scale)))), MUTED_TEXT, _font(10 * scale))
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_chart_overlays(image, layout, chart.title, chart.subtitle, legend_items, chart.legend_title, scale=scale)
        return _png_bytes(_downsample(image, chart.width, chart.height))

    def render_pie_chart_png(self, chart: PieChart) -> bytes:
        scale = RENDER_SCALE
        image = _background_image(chart.width * scale, chart.height * scale)
        draw = ImageDraw.Draw(image, "RGBA")
        slices = tuple(item for item in chart.slices if item.value > 0)
        legend_items = tuple(
            LegendItem(label=item.label, color=item.color or COLORS[index % len(COLORS)], value=item.value, value_format=chart.value_format)
            for index, item in enumerate(slices)
        )
        layout = _chart_overlay_layout(draw, image.width, image.height, chart.title, chart.subtitle, legend_items, scale=scale)
        total = sum(item.value for item in slices)
        center_x = (layout.plot_left + layout.plot_right) // 2
        center_y = (layout.plot_top + layout.plot_bottom) // 2 + 8 * scale
        radius = _pie_radius(_chart_frame_from_layout(layout), center_x, center_y, scale=scale, has_value_label=bool(chart.value_label))
        if total > 0:
            start = -90.0
            bbox = (center_x - radius, center_y - radius, center_x + radius, center_y + radius)
            for index, item in enumerate(slices):
                sweep = item.value / total * 360.0
                color = item.color or COLORS[index % len(COLORS)]
                draw.pieslice(bbox, start=start, end=start + sweep, fill=color)
                start += sweep
            draw.ellipse(bbox, outline=SIDEBAR_BORDER, width=max(1, scale))
        if chart.value_label:
            _draw_text_center(draw, center_x, center_y + radius + 18 * scale, chart.value_label, MUTED_TEXT, _font(12 * scale))
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_chart_overlays(image, layout, chart.title, chart.subtitle, legend_items, chart.legend_title, scale=scale)
        return _png_bytes(_downsample(image, chart.width, chart.height))

    def render_route_map_png(self, chart: RouteMap) -> bytes:
        scale = RENDER_SCALE
        width, height = chart.width, chart.height
        projected_routes = tuple(_project_route(route) for route in chart.routes if len(route.points) >= 2)
        if chart.x_domain is not None and chart.y_domain is not None:
            x_domain, y_domain = chart.x_domain, chart.y_domain
        else:
            from visualization.render import route_map_viewport

            viewport = route_map_viewport(chart.routes, width=width, height=height)
            x_domain, y_domain = viewport.x_domain, viewport.y_domain
        background = _route_background(chart, x_domain, y_domain, width * scale, height * scale)
        image = background.convert("RGBA")
        draw = ImageDraw.Draw(image, "RGBA")
        for index, (route, points) in enumerate(projected_routes):
            color = COLORS[index % len(COLORS)]
            pixel_points = [
                (
                    _scale_float(x_value, x_domain, 0, width * scale - 1),
                    _scale_float(y_value, y_domain, 0, height * scale - 1),
                )
                for x_value, y_value in points
            ]
            if len(pixel_points) >= 2:
                if chart.color_domain is not None and route.color_metric:
                    draw.line(pixel_points, fill=(255, 255, 255, 190), width=8 * scale, joint="curve")
                    _draw_colored_route_segments(
                        draw,
                        route,
                        pixel_points,
                        chart.color_domain,
                        fallback=(100, 116, 139),
                        direction=chart.color_direction,
                        scale=scale,
                    )
                else:
                    draw.line(pixel_points, fill=color + (255,), width=6 * scale, joint="curve")
                    draw.line(pixel_points, fill=(255, 255, 255, 160), width=2 * scale, joint="curve")
                    draw.line(pixel_points, fill=color + (255,), width=3 * scale, joint="curve")
            _draw_marker(draw, pixel_points[0], (22, 163, 74), scale=scale)
            _draw_marker(draw, pixel_points[-1], (220, 38, 38), scale=scale)
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_route_overlays(image, image.width, image.height, chart, scale=scale)
        if chart.attribution:
            _draw_attribution(draw, image.width, image.height, chart.attribution, scale=scale)
        return _png_bytes(_downsample(image, width, height))


def _project_route(route: RoutePolyline) -> tuple[RoutePolyline, tuple[tuple[float, float], ...]]:
    return route, tuple(_mercator_xy(point.latitude, point.longitude) for point in route.points)


def _draw_colored_route_segments(
    draw: ImageDraw.ImageDraw,
    route: RoutePolyline,
    pixel_points: list[tuple[float, float]],
    color_domain: tuple[float, float],
    *,
    fallback: tuple[int, int, int],
    direction: str,
    scale: int,
) -> None:
    line_width = 6 * scale
    joint_radius = line_width / 2.0
    for index, (current, following) in enumerate(zip(pixel_points, pixel_points[1:], strict=False)):
        first = route.points[index].color_value
        second = route.points[index + 1].color_value
        if first is not None:
            color = route_metric_color(first, color_domain, direction=direction)
        elif second is not None:
            color = route_metric_color(second, color_domain, direction=direction)
        else:
            color = fallback
        draw.line((current, following), fill=color + (255,), width=line_width)
        _draw_route_joint(draw, current, joint_radius, color)
        _draw_route_joint(draw, following, joint_radius, color)


def _draw_route_joint(draw: ImageDraw.ImageDraw, point: tuple[float, float], radius: float, color: tuple[int, int, int]) -> None:
    x, y = point
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color + (255,))


def _route_background(chart: RouteMap, x_domain: tuple[float, float], y_domain: tuple[float, float], width: int, height: int) -> Image.Image:
    if chart.tile_zoom is None or not chart.tiles:
        image = _background_image(width, height).convert("RGB")
        draw = ImageDraw.Draw(image)
        _draw_map_grid(draw, 0, 0, width - 1, height - 1, scale=max(1, width // max(chart.width, 1)))
        return image
    decoded: dict[tuple[int, int], Image.Image] = {}
    for tile in chart.tiles:
        try:
            decoded[(tile.coord.x, tile.coord.y)] = Image.open(BytesIO(tile.content)).convert("RGB")
        except OSError:
            continue
    if not decoded:
        return _background_image(width, height).convert("RGB")
    tile_size = chart.tile_size
    n = 2**chart.tile_zoom
    world_size = n * tile_size
    left = x_domain[0] * world_size
    top = y_domain[0] * world_size
    right = x_domain[1] * world_size
    bottom = y_domain[1] * world_size
    x_min = math.floor(left / tile_size)
    y_min = math.floor(top / tile_size)
    x_max = math.floor((right - 1e-9) / tile_size)
    y_max = math.floor((bottom - 1e-9) / tile_size)
    mosaic = Image.new("RGB", ((x_max - x_min + 1) * tile_size, (y_max - y_min + 1) * tile_size), (230, 236, 243))
    for (x, y), tile_image in decoded.items():
        if x_min <= x <= x_max and y_min <= y <= y_max:
            if tile_image.size != (tile_size, tile_size):
                tile_image = tile_image.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
            mosaic.paste(tile_image, ((x - x_min) * tile_size, (y - y_min) * tile_size))
    crop = (
        round(left - x_min * tile_size),
        round(top - y_min * tile_size),
        round(right - x_min * tile_size),
        round(bottom - y_min * tile_size),
    )
    cropped = mosaic.crop(crop)
    return cropped.resize((width, height), Image.Resampling.LANCZOS)


def _background_image(width: int, height: int) -> Image.Image:
    gradient_width = min(360, max(2, width))
    gradient_height = min(220, max(2, height))
    image = Image.new("RGB", (gradient_width, gradient_height))
    draw = ImageDraw.Draw(image)
    base = (240, 246, 252)
    strength = 0.7
    top_left = (158, 200, 244)
    top_right = (226, 240, 255)
    center = (249, 253, 255)
    bottom_left = (218, 238, 248)
    bottom_right = (130, 216, 202)
    for y in range(gradient_height):
        y_ratio = y / max(gradient_height - 1, 1)
        left_color = _lerp_color(top_left, bottom_left, y_ratio)
        right_color = _lerp_color(top_right, bottom_right, y_ratio)
        for x in range(gradient_width):
            x_ratio = x / max(gradient_width - 1, 1)
            diagonal = (x_ratio + y_ratio) / 2.0
            edge_color = _lerp_color(left_color, right_color, x_ratio)
            center_weight = max(0.0, 1.0 - abs(diagonal - 0.48) * 2.4)
            gradient_color = _lerp_color(edge_color, center, center_weight * 0.05)
            draw.point((x, y), fill=_lerp_color(base, gradient_color, strength))
    return image.resize((width, height), Image.Resampling.BICUBIC).convert("RGBA")


def _draw_image_frame(draw: ImageDraw.ImageDraw, width: int, height: int, *, scale: int) -> None:
    horizontal_inset = 14 * scale
    top_inset = 12 * scale
    bottom_inset = 14 * scale
    line_width = max(3, 3 * scale)
    draw.rectangle(
        (
            horizontal_inset,
            top_inset,
            width - horizontal_inset,
            height - bottom_inset,
        ),
        outline=(15, 23, 42, 170),
        width=line_width,
    )


def _chart_overlay_layout(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    title: str,
    subtitle: str,
    legend_items: tuple[LegendItem, ...],
    *,
    scale: int,
) -> ChartOverlayLayout:
    overlay_scale = 2 * scale
    padding = 16 * scale
    title_left = 14 * scale
    title_top = 12 * scale
    title_width = _title_overlay_width(width, title, scale=scale)
    title_text_width = max(40 * scale, title_width - 2 * padding)
    title_font = _font(22 * overlay_scale, bold=True)
    subtitle_font = _font(12 * overlay_scale)
    title_lines = (_ellipsize_to_width(draw, title, title_text_width, title_font),)
    subtitle_lines = _route_subtitle_lines(draw, subtitle, title_text_width, subtitle_font) if subtitle else ()
    title_height = (86 + 40 * len(subtitle_lines)) * scale if subtitle_lines else 86 * scale
    title_box = (title_left, title_top, title_left + title_width, title_top + title_height)
    legend_box, visible_count = _chart_legend_box(width, height, legend_items, scale=scale)
    dense_legend = legend_box is not None and (legend_box[3] - legend_box[1]) > max(190 * scale, round(height * 0.28))
    plot_left = 92 * scale
    plot_right = width - 48 * scale
    if dense_legend and legend_box is not None:
        plot_right = min(plot_right, legend_box[0] - 34 * scale)
        plot_top = max(title_box[3] + 42 * scale, 112 * scale)
    else:
        overlay_bottom = title_box[3]
        if legend_box is not None:
            overlay_bottom = max(overlay_bottom, legend_box[3])
        plot_top = max(overlay_bottom + 42 * scale, 112 * scale)
    plot_bottom = height - 86 * scale
    if plot_right - plot_left < 240 * scale:
        plot_right = width - 48 * scale
    if plot_bottom - plot_top < 160 * scale:
        plot_top = min(plot_top, max(112 * scale, height - 246 * scale))
    return ChartOverlayLayout(
        plot_left=plot_left,
        plot_top=plot_top,
        plot_right=plot_right,
        plot_bottom=plot_bottom,
        title_box=title_box,
        title_text_width=title_text_width,
        title_lines=title_lines,
        subtitle_lines=subtitle_lines,
        legend_box=legend_box,
        visible_legend_count=visible_count,
    )


def _title_overlay_width(width: int, title: str, *, scale: int) -> int:
    available = max(280 * scale, width - 520 * scale)
    preferred = max(860 * scale, len(title) * 24 * scale)
    return min(available, preferred)


def _chart_legend_box(width: int, height: int, items: tuple[LegendItem, ...], *, scale: int) -> tuple[tuple[int, int, int, int] | None, int]:
    if not items:
        return None, 0
    overlay_width = min(392 * scale, width - 28 * scale)
    left = width - overlay_width - 14 * scale
    top = 12 * scale
    max_bottom = height - 24 * scale
    visible = 0
    content_height = 56 * scale
    for item in items[:20]:
        row_height = (48 if item.note else 34) * scale
        if top + content_height + row_height > max_bottom:
            break
        content_height += row_height
        visible += 1
    if visible == 0:
        visible = 1
        content_height += 34 * scale
    if len(items) > visible:
        content_height = min(content_height + 34 * scale, max_bottom - top)
    return (left, top, width - 14 * scale, top + content_height), visible


def _chart_frame_from_layout(layout: ChartOverlayLayout) -> ChartFrame:
    return ChartFrame(
        title_x=layout.title_box[0],
        title_y=layout.title_box[1],
        subtitle_y=layout.title_box[1],
        plot_left=layout.plot_left,
        plot_top=layout.plot_top,
        plot_right=layout.plot_right,
        plot_bottom=layout.plot_bottom,
        sidebar_left=layout.legend_box[0] if layout.legend_box else layout.plot_right,
        sidebar_top=layout.legend_box[1] if layout.legend_box else layout.plot_top,
        sidebar_right=layout.legend_box[2] if layout.legend_box else layout.plot_right,
        sidebar_bottom=layout.plot_bottom,
    )


def _draw_chart_overlays(
    image: Image.Image,
    layout: ChartOverlayLayout,
    title: str,
    subtitle: str,
    legend_items: tuple[LegendItem, ...],
    legend_title: str,
    *,
    scale: int,
) -> None:
    del title, subtitle
    route_text = (255, 255, 255)
    route_muted_text = (226, 232, 240)
    overlay_scale = 2 * scale
    padding = 16 * scale
    panel_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel_layer, "RGBA")
    _dark_panel(panel_draw, layout.title_box)
    if layout.legend_box is not None and legend_items:
        _dark_panel(panel_draw, layout.legend_box)
    image.alpha_composite(panel_layer)
    draw = ImageDraw.Draw(image, "RGBA")
    title_font = _font(22 * overlay_scale, bold=True)
    subtitle_font = _font(12 * overlay_scale)
    for index, line in enumerate(layout.title_lines):
        _draw_text(draw, layout.title_box[0] + padding, layout.title_box[1] + (10 + index * 44) * scale, line, route_text, title_font)
    for index, line in enumerate(layout.subtitle_lines):
        _draw_text(draw, layout.title_box[0] + padding, layout.title_box[1] + (76 + index * 32) * scale, line, route_muted_text, subtitle_font)
    _draw_overlay_legend(draw, layout, legend_items, legend_title, route_text, route_muted_text, scale=scale)


def _draw_overlay_legend(
    draw: ImageDraw.ImageDraw,
    layout: ChartOverlayLayout,
    items: tuple[LegendItem, ...],
    title: str,
    text_color: tuple[int, int, int],
    muted_color: tuple[int, int, int],
    *,
    scale: int,
) -> None:
    if layout.legend_box is None or not items:
        return
    overlay_scale = 2 * scale
    padding = 16 * scale
    left, top, right, bottom = layout.legend_box
    x = left + padding
    y = top + 10 * scale
    value_x = right - padding
    _draw_text(draw, x, y, title, text_color, _font(12 * overlay_scale, bold=True))
    y += 42 * scale
    for item in items[: layout.visible_legend_count]:
        if item.line:
            draw.line((x, y + 11 * scale, x + 36 * scale, y + 11 * scale), fill=item.color, width=max(8, 4 * scale))
        else:
            draw.rectangle((x, y + 4 * scale, x + 20 * scale, y + 24 * scale), fill=item.color)
        label_left = x + 52 * scale
        label_right = value_x - (72 * scale if item.value is not None else 0)
        label_width = max(40 * scale, label_right - label_left)
        _draw_text(draw, label_left, y - 2 * scale, _ellipsize_to_width(draw, item.label, label_width, _font(11 * overlay_scale)), text_color, _font(11 * overlay_scale))
        if item.value is not None:
            _draw_text_right(draw, value_x, y - 2 * scale, _format_tick(item.value, tick_format=item.value_format), muted_color, _font(10 * overlay_scale))
        if item.note:
            y += 22 * scale
            _draw_text(draw, label_left, y - 2 * scale, _ellipsize_to_width(draw, item.note, value_x - label_left, _font(9 * overlay_scale)), muted_color, _font(9 * overlay_scale))
            y += 26 * scale
        else:
            y += 34 * scale
    if len(items) > layout.visible_legend_count and y < bottom - 20 * scale:
        _draw_text(draw, x + 52 * scale, y - 2 * scale, "...", muted_color, _font(11 * overlay_scale))


def _draw_frame(draw: ImageDraw.ImageDraw, frame: ChartFrame, width: int, height: int, title: str, subtitle: str, *, scale: int) -> None:
    draw.rectangle((frame.sidebar_left, frame.sidebar_top, frame.sidebar_right, frame.sidebar_bottom), fill=SIDEBAR_BG)
    draw.line((frame.sidebar_left, frame.sidebar_top, frame.sidebar_left, frame.sidebar_bottom), fill=SIDEBAR_BORDER, width=max(1, scale))
    _draw_text(draw, frame.title_x, frame.title_y, title, TEXT, _font(22 * scale, bold=True))
    if subtitle:
        _draw_text(draw, frame.title_x, frame.subtitle_y, subtitle, MUTED_TEXT, _font(12 * scale))


def _draw_axes(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    x_axis,
    y_axis,
    x_label: str,
    y_label: str,
    *,
    x_tick_format: str,
    y_tick_format: str,
    invert_y: bool,
    scale: int,
    draw_x_text: bool = True,
) -> None:
    draw.line((left, bottom, right, bottom), fill=(30, 30, 30), width=max(1, scale))
    draw.line((left, top, left, bottom), fill=(30, 30, 30), width=max(1, scale))
    if draw_x_text:
        for tick in x_axis.ticks:
            x = _scale(tick, x_axis.domain, left, right)
            draw.line((x, bottom, x, bottom + 5 * scale), fill=(30, 30, 30), width=max(1, scale))
            _draw_text_center(draw, x, bottom + 12 * scale, _format_tick(tick, tick_format=x_tick_format), MUTED_TEXT, _font(10 * scale))
        if x_label:
            _draw_text_center(draw, (left + right) // 2, bottom + 42 * scale, x_label, MUTED_TEXT, _font(12 * scale))
    _draw_y_axis(draw, left, top, right, bottom, y_axis, y_label, y_tick_format, invert_y=invert_y, scale=scale)


def _draw_y_axis(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    right: int,
    bottom: int,
    axis,
    label: str,
    tick_format: str,
    *,
    invert_y: bool = False,
    scale: int,
) -> None:
    for tick in axis.ticks:
        y = _scale_y(tick, axis.domain, bottom, top, invert=invert_y)
        draw.line((left - 5 * scale, y, left, y), fill=(30, 30, 30), width=max(1, scale))
        draw.line((left + 1, y, right, y), fill=GRID, width=max(1, scale))
        _draw_text_right(draw, left - 10 * scale, y - 5 * scale, _format_tick(tick, tick_format=tick_format), MUTED_TEXT, _font(10 * scale))
    if label:
        _draw_text(draw, left, top - 20 * scale, label, MUTED_TEXT, _font(12 * scale))


def _draw_series(
    draw: ImageDraw.ImageDraw,
    x_values: tuple[float | None, ...],
    y_values: tuple[float | None, ...],
    *,
    x_axis,
    y_axis,
    left: int,
    right: int,
    top: int,
    bottom: int,
    color: tuple[int, int, int],
    invert_y: bool,
    scale: int,
) -> None:
    points: list[tuple[int, int]] = []
    show_markers = _show_markers(x_values, y_values)
    for x_value, y_value in zip(x_values, y_values, strict=False):
        if x_value is None or y_value is None:
            if len(points) >= 2:
                draw.line(points, fill=color, width=max(2, 2 * scale), joint="curve")
            points = []
            continue
        x = _scale(x_value, x_axis.domain, left, right)
        y = _scale_y(y_value, y_axis.domain, bottom, top, invert=invert_y)
        points.append((x, y))
        if show_markers:
            radius = 3 * scale
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
    if len(points) >= 2:
        draw.line(points, fill=color, width=max(2, 2 * scale), joint="curve")


def _draw_sidebar_legend(draw: ImageDraw.ImageDraw, frame: ChartFrame, items: tuple[LegendItem, ...], title: str, *, scale: int) -> None:
    if not items:
        return
    x = frame.sidebar_left + 18 * scale
    y = frame.sidebar_top + 18 * scale
    value_x = frame.sidebar_right - 18 * scale
    _draw_text(draw, x, y, title, TEXT, _font(12 * scale, bold=True))
    y += 28 * scale
    for item in items:
        if y > frame.sidebar_bottom - 22 * scale:
            _draw_text(draw, x, y, "...", MUTED_TEXT, _font(12 * scale))
            return
        if item.line:
            draw.line((x, y + 6 * scale, x + 16 * scale, y + 6 * scale), fill=item.color, width=max(2, scale))
        else:
            draw.rectangle((x, y, x + 12 * scale, y + 12 * scale), fill=item.color)
        _draw_text(draw, x + 22 * scale, y - 1 * scale, _ellipsize(item.label, 18), TEXT, _font(11 * scale))
        if item.value is not None:
            _draw_text_right(draw, value_x, y - 1 * scale, _format_tick(item.value, tick_format=item.value_format), MUTED_TEXT, _font(10 * scale))
        if item.note:
            y += 14 * scale
            _draw_text(draw, x + 22 * scale, y - 1 * scale, _ellipsize(item.note, 24), MUTED_TEXT, _font(10 * scale))
        y += 22 * scale


def _draw_route_overlays(image: Image.Image, width: int, height: int, chart: RouteMap, *, scale: int) -> None:
    panel_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel_layer, "RGBA")
    overlay_scale = 2 * scale
    padding = 16 * scale
    route_text = (255, 255, 255)
    route_muted_text = (226, 232, 240)
    title_width = min(width - 520 * scale, max(860 * scale, len(chart.title) * 24 * scale))
    title_left = 14 * scale
    title_top = 12 * scale
    title_text_width = max(40 * scale, title_width - 2 * padding)
    title_font = _font(22 * overlay_scale, bold=True)
    subtitle_font = _font(12 * overlay_scale)
    subtitle_lines = _route_subtitle_lines(panel_draw, chart.subtitle, title_text_width, subtitle_font) if chart.subtitle else ()
    title_height = (86 + 40 * len(subtitle_lines)) * scale if subtitle_lines else 86 * scale
    _dark_panel(panel_draw, (title_left, title_top, title_width, title_top + title_height))
    if chart.routes:
        overlay_width = 392 * scale
        color_scale_only = chart.color_metric_label and chart.color_domain is not None
        visible_route_count = 0 if color_scale_only else _visible_route_legend_count(len(chart.routes), height, scale=scale)
        overlay_height = min(
            (86 * scale if color_scale_only else 84 * scale + visible_route_count * 44 * scale),
            height - 24 * scale,
        )
        left = width - overlay_width - 14 * scale
        top = 12 * scale
        _dark_panel(panel_draw, (left, top, width - 14 * scale, top + overlay_height))
    image.alpha_composite(panel_layer)

    draw = ImageDraw.Draw(image, "RGBA")
    _draw_text(
        draw,
        title_left + padding,
        title_top + 10 * scale,
        _ellipsize_to_width(draw, chart.title, title_text_width, title_font),
        route_text,
        title_font,
    )
    for index, line in enumerate(subtitle_lines):
        _draw_text(
            draw,
            title_left + padding,
            title_top + (76 + index * 32) * scale,
            line,
            route_muted_text,
            subtitle_font,
        )
    if not chart.routes:
        return
    overlay_width = 392 * scale
    color_scale_only = chart.color_metric_label and chart.color_domain is not None
    visible_route_count = 0 if color_scale_only else _visible_route_legend_count(len(chart.routes), height, scale=scale)
    overlay_height = min(
        (86 * scale if color_scale_only else 84 * scale + visible_route_count * 44 * scale),
        height - 24 * scale,
    )
    left = width - overlay_width - 14 * scale
    top = 12 * scale
    if color_scale_only:
        _draw_route_color_scale(draw, left + padding, top + 10 * scale, chart, route_text, route_muted_text, scale=scale)
        return
    _draw_text(draw, left + padding, top + 10 * scale, chart.legend_title, route_text, _font(12 * overlay_scale, bold=True))
    y = top + 66 * scale
    for index, route in enumerate(chart.routes[:visible_route_count]):
        color = route.color or COLORS[index % len(COLORS)]
        draw.line((left + padding, y + 12 * scale, left + padding + 36 * scale, y + 12 * scale), fill=color, width=max(12, 6 * scale))
        _draw_text(draw, left + padding + 52 * scale, y - 2 * scale, _ellipsize(route.label, 28), route_text, _font(11 * overlay_scale))
        y += 44 * scale
    if len(chart.routes) > visible_route_count:
        _draw_text(draw, left + padding + 52 * scale, y - 2 * scale, "...", route_muted_text, _font(11 * overlay_scale))
        y += 44 * scale


def _visible_route_legend_count(route_count: int, height: int, *, scale: int) -> int:
    if route_count <= 0:
        return 0
    available_rows = max(1, (height - 108 * scale) // (44 * scale))
    return min(route_count, 20, available_rows)


def _route_color_scale_height(chart: RouteMap, *, scale: int) -> int:
    return 54 * scale if chart.color_metric_label and chart.color_domain is not None else 0


def _draw_route_color_scale(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    chart: RouteMap,
    text_color: tuple[int, int, int],
    muted_color: tuple[int, int, int],
    *,
    scale: int,
) -> None:
    if chart.color_domain is None:
        return
    font = _font(10 * 2 * scale)
    _draw_text(draw, left, top, chart.color_metric_label, text_color, font)
    bar_top = top + 26 * scale
    bar_width = 170 * scale
    bar_height = 7 * scale
    for offset in range(bar_width):
        ratio = offset / max(bar_width - 1, 1)
        value = chart.color_domain[0] + (chart.color_domain[1] - chart.color_domain[0]) * ratio
        color = route_metric_color(value, chart.color_domain, direction=chart.color_direction)
        draw.line((left + offset, bar_top, left + offset, bar_top + bar_height), fill=color + (255,), width=1)
    low = _format_tick(chart.color_domain[0], tick_format=chart.color_tick_format)
    high = _format_tick(chart.color_domain[1], tick_format=chart.color_tick_format)
    _draw_text(draw, left, bar_top + 12 * scale, low, muted_color, _font(8 * 2 * scale))
    _draw_text_right(draw, left + bar_width, bar_top + 12 * scale, high, muted_color, _font(8 * 2 * scale))


def _draw_attribution(draw: ImageDraw.ImageDraw, width: int, height: int, attribution: str, *, scale: int) -> None:
    font = _font(10 * scale)
    text_width = min(260 * scale, max(160 * scale, _text_size(draw, attribution, font)[0]))
    left = width - text_width - 8 * scale
    top = height - 24 * scale
    _panel(draw, (left, top, width - 6 * scale, height - 7 * scale))
    _draw_text_right(draw, width - 10 * scale, height - 21 * scale, attribution, TEXT, font)


def _draw_map_grid(draw: ImageDraw.ImageDraw, left: int, top: int, right: int, bottom: int, *, scale: int) -> None:
    draw.line((left, bottom, right, bottom), fill=(88, 96, 110), width=max(1, scale))
    draw.line((left, top, left, bottom), fill=(88, 96, 110), width=max(1, scale))
    for index in range(1, 5):
        x = left + (right - left) * index // 5
        y = top + (bottom - top) * index // 5
        draw.line((x, top, x, bottom), fill=(214, 222, 232), width=max(1, scale))
        draw.line((left, y, right, y), fill=(214, 222, 232), width=max(1, scale))


def _panel(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int]) -> None:
    draw.rectangle(bbox, fill=SIDEBAR_BG + (235,), outline=SIDEBAR_BORDER + (255,))


def _dark_panel(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int]) -> None:
    draw.rectangle(bbox, fill=(15, 23, 42, 174), outline=(148, 163, 184, 110))


def _draw_marker(draw: ImageDraw.ImageDraw, point: tuple[float, float], color: tuple[int, int, int], *, scale: int) -> None:
    x, y = point
    radius = 5 * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 230), outline=color + (255,), width=2 * scale)
    inner = 2 * scale
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=color + (255,))


def _scale_float(value: float, domain: tuple[float, float], low_px: int, high_px: int) -> float:
    low, high = domain
    ratio = (value - low) / (high - low)
    return low_px + ratio * (high_px - low_px)


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(start + (end - start) * ratio) for start, end in zip(a, b, strict=True))


def _draw_text(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
    draw.text((x, y), text, fill=color, font=font)


def _draw_text_center(draw: ImageDraw.ImageDraw, center_x: int, y: int, text: str, color: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
    width, _ = _text_size(draw, text, font)
    draw.text((center_x - width // 2, y), text, fill=color, font=font)


def _draw_text_right(draw: ImageDraw.ImageDraw, right_x: int, y: int, text: str, color: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
    width, _ = _text_size(draw, text, font)
    draw.text((right_x - width, y), text, fill=color, font=font)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _ellipsize_to_width(draw: ImageDraw.ImageDraw, text: str, max_width: int, font: ImageFont.ImageFont) -> str:
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    ellipsis = "..."
    if _text_size(draw, ellipsis, font)[0] > max_width:
        return ""
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if _text_size(draw, text[:mid].rstrip() + ellipsis, font)[0] <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + ellipsis


def _route_subtitle_lines(draw: ImageDraw.ImageDraw, subtitle: str, max_width: int, font: ImageFont.ImageFont) -> tuple[str, ...]:
    if not subtitle:
        return ()
    if _text_size(draw, subtitle, font)[0] <= max_width:
        return (subtitle,)
    parts = tuple(part.strip() for part in subtitle.split(" - ") if part.strip())
    split_index = _route_subtitle_split_index(parts)
    if split_index is None:
        return (_ellipsize_to_width(draw, subtitle, max_width, font),)
    first = " - ".join(parts[:split_index])
    second = " - ".join(parts[split_index:])
    return (
        _ellipsize_to_width(draw, first, max_width, font),
        _ellipsize_to_width(draw, second, max_width, font),
    )


def _route_subtitle_split_index(parts: tuple[str, ...]) -> int | None:
    if len(parts) >= 4:
        return 2
    if len(parts) >= 2:
        return (len(parts) + 1) // 2
    return None


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=max(8, size))
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=max(8, size))
    except TypeError:
        return ImageFont.load_default()


def _downsample(image: Image.Image, width: int, height: int) -> Image.Image:
    return image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)


def _png_bytes(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()
