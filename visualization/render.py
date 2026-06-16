from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLORS = (
    (37, 99, 235),
    (22, 163, 74),
    (234, 179, 8),
    (249, 115, 22),
    (220, 38, 38),
    (124, 58, 237),
    (8, 145, 178),
    (190, 24, 93),
)
MARKER_POINT_LIMIT = 80
RENDER_SCALE = 2
TEXT = (34, 39, 46)
MUTED_TEXT = (91, 99, 112)
GRID = (219, 225, 232)
SIDEBAR_BG = (237, 241, 246)
SIDEBAR_BORDER = (210, 218, 228)


@dataclass(frozen=True)
class RenderSeries:
    metric: str
    values: tuple[float | None, ...]
    scaled: bool = False
    clipped: bool = False
    smoothed: bool = False
    label: str = ""


@dataclass(frozen=True)
class LineChart:
    title: str
    x_values: tuple[float | None, ...]
    series: tuple[RenderSeries, ...]
    subtitle: str = ""
    x_label: str = ""
    y_label: str = ""
    x_tick_format: str = "number"
    y_tick_format: str = "number"
    invert_y: bool = False
    width: int = 900
    height: int = 520


@dataclass(frozen=True)
class LinePanel:
    series: RenderSeries
    y_label: str
    y_tick_format: str = "number"
    invert_y: bool = False


@dataclass(frozen=True)
class MultiPanelLineChart:
    title: str
    x_values: tuple[float | None, ...]
    panels: tuple[LinePanel, ...]
    subtitle: str = ""
    x_label: str = ""
    x_tick_format: str = "number"
    width: int = 900
    height: int = 640


@dataclass(frozen=True)
class Bar:
    label: str
    value: float
    color: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class BarChart:
    title: str
    bars: tuple[Bar, ...]
    subtitle: str = ""
    x_label: str = ""
    y_label: str = ""
    y_tick_format: str = "number"
    width: int = 900
    height: int = 520


@dataclass(frozen=True)
class PieSlice:
    label: str
    value: float
    color: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class PieChart:
    title: str
    slices: tuple[PieSlice, ...]
    subtitle: str = ""
    value_label: str = ""
    value_format: str = "number"
    width: int = 900
    height: int = 520


@dataclass(frozen=True)
class ChartFrame:
    title_x: int
    title_y: int
    subtitle_y: int
    plot_left: int
    plot_top: int
    plot_right: int
    plot_bottom: int
    sidebar_left: int
    sidebar_top: int
    sidebar_right: int
    sidebar_bottom: int


@dataclass(frozen=True)
class LegendItem:
    label: str
    color: tuple[int, int, int]
    value: float | None = None
    value_format: str = "number"
    note: str = ""
    line: bool = False


def render_line_chart_png(chart: LineChart) -> bytes:
    scale = RENDER_SCALE
    width, height = chart.width * scale, chart.height * scale
    pixels = _background(width, height)
    frame = _chart_frame(width, height, scale=scale)
    _draw_frame(pixels, width, height, frame, chart.title, chart.subtitle, scale=scale, draw_text=False)
    left, top, right, bottom = frame.plot_left, frame.plot_top, frame.plot_right, frame.plot_bottom
    _line(pixels, width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, width, left, top, left, bottom, (30, 30, 30))

    x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
    y_values = tuple(value for series in chart.series for value in series.values)
    preliminary_y_axis = _robust_axis(y_values, target_ticks=6)
    render_series = tuple(_prepare_render_series(series, preliminary_y_axis) for series in chart.series)
    render_y_values = tuple(value for series in render_series for value in series.values)
    y_axis = _robust_axis(render_y_values, target_ticks=6)
    y_label = chart.y_label
    if len(render_series) == 1:
        y_label = _label_with_suffixes(y_label, render_series[0])
    _draw_x_axis(pixels, width, left, right, bottom, x_axis, chart.x_label, tick_format=chart.x_tick_format, scale=scale, draw_text=False)
    _draw_y_axis(
        pixels,
        width,
        left,
        top,
        bottom,
        y_axis,
        y_label,
        tick_format=chart.y_tick_format,
        invert_y=chart.invert_y,
        grid_right=right,
        scale=scale,
        draw_text=False,
    )
    for index, series in enumerate(render_series):
        color = COLORS[index % len(COLORS)]
        previous: tuple[int, int] | None = None
        show_markers = _show_markers(chart.x_values, series.values)
        for x_value, y_value in zip(chart.x_values, series.values, strict=False):
            if x_value is None or y_value is None:
                previous = None
                continue
            x = _scale(x_value, x_axis.domain, left, right)
            y = _scale_y(y_value, y_axis.domain, bottom, top, invert=chart.invert_y)
            if previous is not None:
                _stroke_line(pixels, width, previous[0], previous[1], x, y, color, stroke=scale)
            if show_markers:
                _dot(pixels, width, x, y, color, scale=scale)
            previous = (x, y)
    output = _downsample(pixels, chart.width, chart.height, scale=scale)
    output_frame = _chart_frame(chart.width, chart.height)
    output_left, output_top, output_right, output_bottom = (
        output_frame.plot_left,
        output_frame.plot_top,
        output_frame.plot_right,
        output_frame.plot_bottom,
    )
    _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
    _draw_x_axis(output, chart.width, output_left, output_right, output_bottom, x_axis, chart.x_label, tick_format=chart.x_tick_format, draw_lines=False)
    _draw_y_axis(
        output,
        chart.width,
        output_left,
        output_top,
        output_bottom,
        y_axis,
        y_label,
        tick_format=chart.y_tick_format,
        invert_y=chart.invert_y,
        grid_right=output_right,
        draw_lines=False,
    )
    _draw_sidebar_legend(output, chart.width, output_frame, _line_legend_items(render_series), title="Legend")
    return _png(chart.width, chart.height, output)


def render_multi_panel_line_chart_png(chart: MultiPanelLineChart) -> bytes:
    scale = RENDER_SCALE
    width, height = chart.width * scale, chart.height * scale
    pixels = _background(width, height)
    frame = _chart_frame(width, height, scale=scale)
    _draw_frame(pixels, width, height, frame, chart.title, chart.subtitle, scale=scale, draw_text=False)
    left, top, right, bottom = frame.plot_left, frame.plot_top, frame.plot_right, frame.plot_bottom
    if not chart.panels:
        output = _downsample(pixels, chart.width, chart.height, scale=scale)
        output_frame = _chart_frame(chart.width, chart.height)
        _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
        return _png(chart.width, chart.height, output)

    x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
    gap = 26 * scale
    panel_count = len(chart.panels)
    panel_height = max(72, (bottom - top - gap * (panel_count - 1)) // panel_count)
    for index, panel in enumerate(chart.panels):
        panel_top = top + index * (panel_height + gap)
        panel_bottom = panel_top + panel_height
        _line(pixels, width, left, panel_bottom, right, panel_bottom, (30, 30, 30))
        _line(pixels, width, left, panel_top, left, panel_bottom, (30, 30, 30))
        preliminary_y_axis = _robust_axis(panel.series.values, target_ticks=5)
        render_series = _prepare_render_series(panel.series, preliminary_y_axis)
        y_axis = _robust_axis(render_series.values, target_ticks=5)
        label = _label_with_suffixes(panel.y_label, render_series)
        _draw_y_axis(
            pixels,
            width,
            left,
            panel_top,
            panel_bottom,
            y_axis,
            label,
            tick_format=panel.y_tick_format,
            invert_y=panel.invert_y,
            grid_right=right,
            scale=scale,
            draw_text=False,
        )
        _draw_panel_series(
            pixels,
            width,
            chart.x_values,
            render_series,
            x_axis=x_axis,
            y_axis=y_axis,
            left=left,
            right=right,
            top=panel_top,
            bottom=panel_bottom,
            color=COLORS[index % len(COLORS)],
            invert_y=panel.invert_y,
            scale=scale,
        )

    _draw_x_axis(
        pixels,
        width,
        left,
        right,
        top + (panel_count - 1) * (panel_height + gap) + panel_height,
        x_axis,
        chart.x_label,
        tick_format=chart.x_tick_format,
        scale=scale,
        draw_text=False,
    )
    output = _downsample(pixels, chart.width, chart.height, scale=scale)
    output_frame = _chart_frame(chart.width, chart.height)
    output_left, output_top, output_right, output_bottom = (
        output_frame.plot_left,
        output_frame.plot_top,
        output_frame.plot_right,
        output_frame.plot_bottom,
    )
    output_gap = 26
    output_panel_height = max(72, (output_bottom - output_top - output_gap * (panel_count - 1)) // panel_count)
    _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
    for index, panel in enumerate(chart.panels):
        panel_top = output_top + index * (output_panel_height + output_gap)
        panel_bottom = panel_top + output_panel_height
        preliminary_y_axis = _robust_axis(panel.series.values, target_ticks=5)
        render_series = _prepare_render_series(panel.series, preliminary_y_axis)
        y_axis = _robust_axis(render_series.values, target_ticks=5)
        label = _label_with_suffixes(panel.y_label, render_series)
        _draw_y_axis(
            output,
            chart.width,
            output_left,
            panel_top,
            panel_bottom,
            y_axis,
            label,
            tick_format=panel.y_tick_format,
            invert_y=panel.invert_y,
            grid_right=output_right,
            draw_lines=False,
        )
    _draw_x_axis(
        output,
        chart.width,
        output_left,
        output_right,
        output_top + (panel_count - 1) * (output_panel_height + output_gap) + output_panel_height,
        x_axis,
        chart.x_label,
        tick_format=chart.x_tick_format,
        draw_lines=False,
    )
    _draw_sidebar_legend(output, chart.width, output_frame, _line_legend_items(tuple(panel.series for panel in chart.panels)), title="Panels")
    return _png(chart.width, chart.height, output)


def render_bar_chart_png(chart: BarChart) -> bytes:
    scale = RENDER_SCALE
    width, height = chart.width * scale, chart.height * scale
    pixels = _background(width, height)
    frame = _chart_frame(width, height, scale=scale)
    _draw_frame(pixels, width, height, frame, chart.title, chart.subtitle, scale=scale, draw_text=False)
    left, top, right, bottom = frame.plot_left, frame.plot_top, frame.plot_right, frame.plot_bottom - 14 * scale
    _line(pixels, width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, width, left, top, left, bottom, (30, 30, 30))
    if not chart.bars:
        output = _downsample(pixels, chart.width, chart.height, scale=scale)
        output_frame = _chart_frame(chart.width, chart.height)
        _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
        return _png(chart.width, chart.height, output)

    y_axis = _axis(tuple(bar.value for bar in chart.bars), target_ticks=6, include_zero=True)
    _draw_y_axis(pixels, width, left, top, bottom, y_axis, chart.y_label, tick_format=chart.y_tick_format, grid_right=right, scale=scale, draw_text=False)
    slot_width = max(1, (right - left) // len(chart.bars))
    bar_width = max(8 * scale, round(slot_width * 0.65))
    for index, bar in enumerate(chart.bars):
        color = bar.color or COLORS[index % len(COLORS)]
        center = left + index * slot_width + slot_width // 2
        x1 = center - bar_width // 2
        x2 = center + bar_width // 2
        y1 = _scale(bar.value, y_axis.domain, bottom, top)
        _rect(pixels, width, x1, y1, x2, bottom - 1, color)
    output = _downsample(pixels, chart.width, chart.height, scale=scale)
    output_frame = _chart_frame(chart.width, chart.height)
    output_left, output_top, output_right, output_bottom = (
        output_frame.plot_left,
        output_frame.plot_top,
        output_frame.plot_right,
        output_frame.plot_bottom - 14,
    )
    _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
    _draw_y_axis(output, chart.width, output_left, output_top, output_bottom, y_axis, chart.y_label, tick_format=chart.y_tick_format, grid_right=output_right, draw_lines=False)
    if chart.x_label:
        _draw_centered_text(output, chart.width, (output_left + output_right) // 2, output_frame.plot_bottom + 48, chart.x_label, MUTED_TEXT)
    output_slot_width = max(1, (output_right - output_left) // len(chart.bars))
    for index, bar in enumerate(chart.bars):
        center = output_left + index * output_slot_width + output_slot_width // 2
        _draw_centered_text(output, chart.width, center, output_bottom + 12, _ellipsize(bar.label, 12), MUTED_TEXT)
    _draw_sidebar_legend(
        output,
        chart.width,
        output_frame,
        tuple(
            LegendItem(label=bar.label, color=bar.color or COLORS[index % len(COLORS)], value=bar.value, value_format=chart.y_tick_format)
            for index, bar in enumerate(chart.bars)
        ),
        title="Legend",
    )
    return _png(chart.width, chart.height, output)


def render_pie_chart_png(chart: PieChart) -> bytes:
    scale = RENDER_SCALE
    width, height = chart.width * scale, chart.height * scale
    pixels = _background(width, height)
    frame = _chart_frame(width, height, scale=scale)
    _draw_frame(pixels, width, height, frame, chart.title, chart.subtitle, scale=scale, draw_text=False)
    all_slices = tuple(item for item in chart.slices if math.isfinite(item.value))
    positive_slices = tuple((index, item) for index, item in enumerate(all_slices) if item.value > 0)
    if not all_slices:
        output = _downsample(pixels, chart.width, chart.height, scale=scale)
        output_frame = _chart_frame(chart.width, chart.height)
        _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
        return _png(chart.width, chart.height, output)

    center_x = (frame.plot_left + frame.plot_right) // 2
    center_y = (frame.plot_top + frame.plot_bottom) // 2 + 8 * scale
    radius = _pie_radius(frame, center_x, center_y, scale=scale, has_value_label=bool(chart.value_label))
    total = sum(item.value for _, item in positive_slices)
    start_angle = -math.pi / 2
    if total > 0:
        for original_index, item in positive_slices:
            end_angle = start_angle + (item.value / total) * math.tau
            color = item.color or COLORS[original_index % len(COLORS)]
            _sector(pixels, width, center_x, center_y, radius, start_angle, end_angle, color)
            start_angle = end_angle
        _circle_outline(pixels, width, center_x, center_y, radius, (30, 30, 30), stroke=scale)
    output = _downsample(pixels, chart.width, chart.height, scale=scale)
    output_frame = _chart_frame(chart.width, chart.height)
    output_center_x = (output_frame.plot_left + output_frame.plot_right) // 2
    output_center_y = (output_frame.plot_top + output_frame.plot_bottom) // 2 + 8
    output_radius = _pie_radius(output_frame, output_center_x, output_center_y, scale=1, has_value_label=bool(chart.value_label))
    _draw_frame(output, chart.width, chart.height, output_frame, chart.title, chart.subtitle, draw_panel=False)
    _draw_sidebar_legend(
        output,
        chart.width,
        output_frame,
        tuple(
            LegendItem(label=item.label, color=item.color or COLORS[index % len(COLORS)], value=item.value, value_format=chart.value_format)
            for index, item in enumerate(all_slices)
        ),
        title="Legend",
    )
    if chart.value_label:
        _draw_centered_text(output, chart.width, output_center_x, output_center_y + output_radius + 18, chart.value_label, MUTED_TEXT)
    return _png(chart.width, chart.height, output)


def _draw_panel_series(
    pixels: bytearray,
    width: int,
    x_values: tuple[float | None, ...],
    series: RenderSeries,
    *,
    x_axis: Axis,
    y_axis: Axis,
    left: int,
    right: int,
    top: int,
    bottom: int,
    color: tuple[int, int, int],
    invert_y: bool = False,
    scale: int = 1,
) -> None:
    previous: tuple[int, int] | None = None
    show_markers = _show_markers(x_values, series.values)
    for x_value, y_value in zip(x_values, series.values, strict=False):
        if x_value is None or y_value is None:
            previous = None
            continue
        if y_value < y_axis.domain[0] or y_value > y_axis.domain[1]:
            previous = None
            continue
        x = _scale(x_value, x_axis.domain, left, right)
        y = _scale_y(y_value, y_axis.domain, bottom, top, invert=invert_y)
        if previous is not None:
            _stroke_line(pixels, width, previous[0], previous[1], x, y, color, stroke=scale)
        if show_markers:
            _dot(pixels, width, x, y, color, scale=scale)
        previous = (x, y)


def _prepare_render_series(series: RenderSeries, y_axis: Axis) -> RenderSeries:
    values = tuple(_visible_value(value, y_axis) for value in series.values)
    clipped = series.clipped or y_axis.clipped
    smoothed = series.smoothed
    if not smoothed and _should_auto_smooth(values):
        values = _fill_short_gaps(values, max_gap=_auto_smooth_window(values))
        values = _rolling_average(values, window_size=_auto_smooth_window(values))
        smoothed = True
    return RenderSeries(
        metric=series.metric,
        values=values,
        scaled=series.scaled,
        clipped=clipped,
        smoothed=smoothed,
        label=series.label,
    )


def _visible_value(value: float | None, y_axis: Axis) -> float | None:
    if value is None:
        return None
    if value < y_axis.domain[0] or value > y_axis.domain[1]:
        return None
    return value


def _label_with_suffixes(label: str, series: RenderSeries) -> str:
    suffixes = []
    if series.clipped:
        suffixes.append("clipped")
    if series.smoothed:
        suffixes.append("smoothed")
    if not suffixes:
        return label
    return f"{label} {', '.join(suffixes)}"


def _chart_frame(width: int, height: int, *, scale: int = 1) -> ChartFrame:
    margin_left = 92 * scale
    title_x = 24 * scale
    plot_top = 92 * scale
    plot_bottom = height - 86 * scale
    sidebar_width = max(190 * scale, round(width * 0.25))
    sidebar_right = width - 1
    sidebar_left = sidebar_right - sidebar_width
    plot_right = sidebar_left - 34 * scale
    return ChartFrame(
        title_x=title_x,
        title_y=18 * scale,
        subtitle_y=42 * scale,
        plot_left=margin_left,
        plot_top=plot_top,
        plot_right=plot_right,
        plot_bottom=plot_bottom,
        sidebar_left=sidebar_left,
        sidebar_top=0,
        sidebar_right=sidebar_right,
        sidebar_bottom=height - 1,
    )


def _draw_frame(
    pixels: bytearray,
    width: int,
    height: int,
    frame: ChartFrame,
    title: str,
    subtitle: str,
    *,
    scale: int = 1,
    draw_panel: bool = True,
    draw_text: bool = True,
) -> None:
    del height
    if draw_panel:
        _rect(pixels, width, frame.sidebar_left, frame.sidebar_top, frame.sidebar_right, frame.sidebar_bottom, SIDEBAR_BG)
        _line(pixels, width, frame.sidebar_left, frame.sidebar_top, frame.sidebar_left, frame.sidebar_bottom, SIDEBAR_BORDER)
    if not draw_text:
        return
    _draw_chart_text(pixels, width, frame.title_x, frame.title_y, title, TEXT, scale=2 * scale)
    if subtitle:
        _draw_chart_text(pixels, width, frame.title_x, frame.subtitle_y, subtitle, MUTED_TEXT, scale=scale)


def _line_legend_items(series: tuple[RenderSeries, ...]) -> tuple[LegendItem, ...]:
    items = []
    for index, item in enumerate(series):
        notes = []
        if item.scaled:
            notes.append("scaled")
        if item.clipped:
            notes.append("clipped")
        if item.smoothed:
            notes.append("smoothed")
        items.append(
            LegendItem(
                label=item.label or item.metric,
                color=COLORS[index % len(COLORS)],
                note=", ".join(notes),
                line=True,
            )
        )
    return tuple(items)


def _draw_sidebar_legend(
    pixels: bytearray,
    width: int,
    frame: ChartFrame,
    items: tuple[LegendItem, ...],
    *,
    title: str,
    scale: int = 1,
) -> None:
    if not items:
        return
    x = frame.sidebar_left + 18 * scale
    y = frame.sidebar_top + 18 * scale
    value_x = frame.sidebar_right - 18 * scale
    _draw_chart_text(pixels, width, x, y, title, TEXT, scale=scale)
    y += 28 * scale
    for item in items:
        if y > frame.sidebar_bottom - 20 * scale:
            _draw_chart_text(pixels, width, x, y, "...", MUTED_TEXT, scale=scale)
            return
        if item.line:
            _stroke_line(pixels, width, x, y + 6 * scale, x + 16 * scale, y + 6 * scale, item.color, stroke=scale)
        else:
            _rect(pixels, width, x, y, x + 12 * scale, y + 12 * scale, item.color)
        label = _ellipsize(item.label, 18)
        _draw_chart_text(pixels, width, x + 22 * scale, y + 2 * scale, label, TEXT, scale=scale)
        if item.value is not None:
            value = _format_tick(item.value, tick_format=item.value_format)
            _draw_right_aligned_text(pixels, width, value_x, y + 2 * scale, value, MUTED_TEXT, scale=scale)
        if item.note:
            y += 14 * scale
            _draw_chart_text(pixels, width, x + 22 * scale, y + 2 * scale, _ellipsize(item.note, 24), MUTED_TEXT, scale=scale)
        y += 22 * scale


def _pie_radius(frame: ChartFrame, center_x: int, center_y: int, *, scale: int, has_value_label: bool) -> int:
    label_space = 36 * scale if has_value_label else 12 * scale
    bottom_limit = frame.sidebar_bottom - 18 * scale
    return max(
        24 * scale,
        min(
            center_x - frame.plot_left - 8 * scale,
            frame.plot_right - center_x - 8 * scale,
            center_y - frame.plot_top - 8 * scale,
            bottom_limit - center_y - label_space,
        ),
    )


def _blank(width: int, height: int, color: tuple[int, int, int]) -> bytearray:
    return bytearray(color * width * height)


def _background(width: int, height: int) -> bytearray:
    pixels = bytearray()
    top = (232, 238, 246)
    middle = (250, 252, 255)
    bottom = (239, 244, 249)
    for y in range(height):
        ratio = y / max(height - 1, 1)
        if ratio <= 0.5:
            local = ratio / 0.5
            color = _lerp_color(top, middle, local)
        else:
            local = (ratio - 0.5) / 0.5
            color = _lerp_color(middle, bottom, local)
        pixels.extend(color * width)
    return pixels


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int], ratio: float) -> tuple[int, int, int]:
    return tuple(round(start + (end - start) * ratio) for start, end in zip(a, b, strict=True))


def _show_markers(x_values: tuple[float | None, ...], y_values: tuple[float | None, ...]) -> bool:
    visible_points = sum(1 for x, y in zip(x_values, y_values, strict=False) if x is not None and y is not None)
    return visible_points <= MARKER_POINT_LIMIT


def _domain(values: tuple[float | None, ...]) -> tuple[float, float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return (0.0, 1.0)
    low = min(numeric)
    high = max(numeric)
    if low == high:
        return (low - 1.0, high + 1.0)
    return (low, high)


@dataclass(frozen=True)
class Axis:
    domain: tuple[float, float]
    ticks: tuple[float, ...]
    clipped: bool = False


def _axis(values: tuple[float | None, ...], *, target_ticks: int, include_zero: bool = False) -> Axis:
    numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if include_zero:
        numeric.append(0.0)
    if not numeric:
        return Axis(domain=(0.0, 1.0), ticks=(0.0, 0.5, 1.0))
    low = min(numeric)
    high = max(numeric)
    if low == high:
        padding = _nice_step(abs(low) or 1.0, round_=False)
        low -= padding
        high += padding
    step = _nice_step((high - low) / max(target_ticks - 1, 1), round_=True)
    domain_low, domain_high = _rounded_domain(low, high, step)
    while _tick_count(domain_low, domain_high, step) > target_ticks + 2:
        step = _next_nice_step(step)
        domain_low, domain_high = _rounded_domain(low, high, step)
    if include_zero:
        domain_low = min(domain_low, 0.0)
        domain_high = max(domain_high, 0.0)
    ticks: list[float] = []
    value = domain_low
    guard = 0
    while value <= domain_high + step / 2 and guard < 50:
        ticks.append(_clean_float(value))
        value += step
        guard += 1
    return Axis(domain=(_clean_float(domain_low), _clean_float(domain_high)), ticks=tuple(ticks))


def _robust_axis(values: tuple[float | None, ...], *, target_ticks: int) -> Axis:
    numeric = sorted(float(value) for value in values if value is not None and math.isfinite(float(value)))
    if len(numeric) < 8:
        return _axis(values, target_ticks=target_ticks)
    q1 = _percentile(numeric, 0.25)
    q3 = _percentile(numeric, 0.75)
    iqr = q3 - q1
    if iqr <= 0:
        return _axis(values, target_ticks=target_ticks)
    full_range = numeric[-1] - numeric[0]
    if full_range <= iqr * 10:
        return _axis(values, target_ticks=target_ticks)
    lower_fence = q1 - iqr * 6
    upper_fence = q3 + iqr * 6
    robust_values = tuple(value for value in numeric if lower_fence <= value <= upper_fence)
    if len(robust_values) == len(numeric) or len(robust_values) < 2:
        return _axis(values, target_ticks=target_ticks)
    axis = _axis(robust_values, target_ticks=target_ticks)
    return Axis(domain=axis.domain, ticks=axis.ticks, clipped=True)


def _should_auto_smooth(values: tuple[float | None, ...]) -> bool:
    numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if len(numeric) < 120:
        return False
    iqr = _interquartile_range(sorted(numeric))
    if iqr <= 0:
        return False
    deltas = [
        abs(current - previous)
        for previous, current in zip(values, values[1:], strict=False)
        if previous is not None and current is not None
    ]
    if not deltas:
        return False
    roughness_ratio = _median(sorted(deltas)) / iqr
    return roughness_ratio >= 0.35


def _auto_smooth_window(values: tuple[float | None, ...]) -> int:
    visible_points = sum(1 for value in values if value is not None)
    window = max(3, min(15, (visible_points // 60) * 2 + 1))
    return window if window % 2 == 1 else window + 1


def _rolling_average(values: tuple[float | None, ...], *, window_size: int) -> tuple[float | None, ...]:
    radius = window_size // 2
    smoothed: list[float | None] = []
    for index, value in enumerate(values):
        if value is None:
            smoothed.append(None)
            continue
        start = max(0, index - radius)
        end = min(len(values), index + radius + 1)
        window = [candidate for candidate in values[start:end] if candidate is not None]
        smoothed.append(sum(window) / len(window) if window else None)
    return tuple(smoothed)


def _fill_short_gaps(values: tuple[float | None, ...], *, max_gap: int) -> tuple[float | None, ...]:
    filled = list(values)
    index = 0
    while index < len(filled):
        if filled[index] is not None:
            index += 1
            continue
        start = index
        while index < len(filled) and filled[index] is None:
            index += 1
        end = index
        gap_size = end - start
        if gap_size > max_gap or start == 0 or end >= len(filled):
            continue
        left = filled[start - 1]
        right = filled[end]
        if left is None or right is None:
            continue
        for offset in range(gap_size):
            ratio = (offset + 1) / (gap_size + 1)
            filled[start + offset] = left + (right - left) * ratio
    return tuple(filled)


def _interquartile_range(sorted_values: list[float]) -> float:
    return _percentile(sorted_values, 0.75) - _percentile(sorted_values, 0.25)


def _median(sorted_values: list[float]) -> float:
    return _percentile(sorted_values, 0.5)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    ratio = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * ratio


def _time_axis(values: tuple[float | None, ...], *, target_ticks: int) -> Axis:
    numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not numeric:
        return Axis(domain=(0.0, 60.0), ticks=(0.0, 60.0))
    low = min(0.0, min(numeric))
    high = max(numeric)
    if high <= low:
        high = low + 60.0
    candidates = (30, 60, 120, 300, 600, 900, 1200, 1800, 3600, 7200)
    step = candidates[-1]
    for candidate in candidates:
        if math.ceil((high - low) / candidate) + 1 <= target_ticks + 2:
            step = candidate
            break
    domain_low = math.floor(low / step) * step
    domain_high = math.ceil(high / step) * step
    ticks = tuple(float(value) for value in range(int(domain_low), int(domain_high) + step, step))
    return Axis(domain=(float(domain_low), float(domain_high)), ticks=ticks)


def _rounded_domain(low: float, high: float, step: float) -> tuple[float, float]:
    return (math.floor(low / step) * step, math.ceil(high / step) * step)


def _tick_count(low: float, high: float, step: float) -> int:
    return math.floor(((high - low) / step) + 1e-9) + 1


def _next_nice_step(step: float) -> float:
    exponent = math.floor(math.log10(step))
    fraction = step / (10 ** exponent)
    if fraction < 2:
        return 2 * (10 ** exponent)
    if fraction < 5:
        return 5 * (10 ** exponent)
    return 10 * (10 ** exponent)


def _nice_step(value: float, *, round_: bool) -> float:
    if value <= 0 or not math.isfinite(value):
        return 1.0
    exponent = math.floor(math.log10(value))
    fraction = value / (10 ** exponent)
    if round_:
        nice_fraction = 1 if fraction < 1.5 else 2 if fraction < 3 else 5 if fraction < 7 else 10
    else:
        nice_fraction = 1 if fraction <= 1 else 2 if fraction <= 2 else 5 if fraction <= 5 else 10
    return nice_fraction * (10 ** exponent)


def _clean_float(value: float) -> float:
    if abs(value) < 1e-10:
        return 0.0
    return round(value, 10)


def _draw_x_axis(
    pixels: bytearray,
    width: int,
    left: int,
    right: int,
    bottom: int,
    axis: Axis,
    label: str,
    *,
    tick_format: str = "number",
    scale: int = 1,
    draw_lines: bool = True,
    draw_text: bool = True,
) -> None:
    for tick in axis.ticks:
        x = _scale(tick, axis.domain, left, right)
        if draw_lines:
            _line(pixels, width, x, bottom, x, bottom + 5 * scale, (30, 30, 30))
        if draw_text:
            _draw_centered_text(
                pixels,
                width,
                x,
                bottom + 12 * scale,
                _format_tick(tick, tick_format=tick_format),
                MUTED_TEXT,
                scale=scale,
            )
    if label and draw_text:
        _draw_centered_text(pixels, width, (left + right) // 2, bottom + 42 * scale, label, MUTED_TEXT, scale=scale)


def _draw_y_axis(
    pixels: bytearray,
    width: int,
    left: int,
    top: int,
    bottom: int,
    axis: Axis,
    label: str,
    *,
    tick_format: str = "number",
    invert_y: bool = False,
    grid_right: int | None = None,
    scale: int = 1,
    draw_lines: bool = True,
    draw_text: bool = True,
) -> None:
    if grid_right is None:
        grid_right = width - 34 * scale
    for tick in axis.ticks:
        y = _scale_y(tick, axis.domain, bottom, top, invert=invert_y)
        if draw_lines:
            _line(pixels, width, left - 5 * scale, y, left, y, (30, 30, 30))
            _line(pixels, width, left + 1, y, grid_right, y, GRID)
        if draw_text:
            _draw_right_aligned_text(
                pixels,
                width,
                left - 10 * scale,
                y - 4 * scale,
                _format_tick(tick, tick_format=tick_format),
                MUTED_TEXT,
                scale=scale,
            )
    if label and draw_text:
        _draw_chart_text(pixels, width, left, top - 18 * scale, label, MUTED_TEXT, scale=scale)


def _format_tick(value: float, *, tick_format: str = "number") -> str:
    if tick_format == "duration":
        return _format_seconds(value)
    if tick_format == "pace":
        return _format_pace(value)
    if tick_format == "percentage":
        return f"{_format_tick(value)}%"
    if abs(value - round(value)) < 1e-8:
        return str(int(round(value)))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text


def _format_seconds(value: float) -> str:
    seconds = max(0, int(round(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_pace(value: float) -> str:
    seconds = max(0, int(round(value)))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _ellipsize(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 1)] + "."


def _scale(value: float, domain: tuple[float, float], low_px: int, high_px: int) -> int:
    low, high = domain
    ratio = (value - low) / (high - low)
    return round(low_px + ratio * (high_px - low_px))


def _scale_y(value: float, domain: tuple[float, float], bottom_px: int, top_px: int, *, invert: bool) -> int:
    if invert:
        return _scale(value, domain, top_px, bottom_px)
    return _scale(value, domain, bottom_px, top_px)


def _dot(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int], *, scale: int = 1) -> None:
    radius = 2 * scale
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            _set(pixels, width, x + dx, y + dy, color)


def _sector(
    pixels: bytearray,
    width: int,
    center_x: int,
    center_y: int,
    radius: int,
    start_angle: float,
    end_angle: float,
    color: tuple[int, int, int],
) -> None:
    radius_squared = radius * radius
    for y in range(center_y - radius, center_y + radius + 1):
        dy = y - center_y
        for x in range(center_x - radius, center_x + radius + 1):
            dx = x - center_x
            if dx * dx + dy * dy > radius_squared:
                continue
            angle = math.atan2(dy, dx)
            if angle < -math.pi / 2:
                angle += math.tau
            if start_angle <= angle <= end_angle:
                _set(pixels, width, x, y, color)


def _circle_outline(
    pixels: bytearray,
    width: int,
    center_x: int,
    center_y: int,
    radius: int,
    color: tuple[int, int, int],
    *,
    stroke: int = 1,
) -> None:
    steps = max(64, radius * 4)
    previous: tuple[int, int] | None = None
    for index in range(steps + 1):
        angle = (index / steps) * math.tau
        x = round(center_x + math.cos(angle) * radius)
        y = round(center_y + math.sin(angle) * radius)
        if previous is not None:
            _stroke_line(pixels, width, previous[0], previous[1], x, y, color, stroke=stroke)
        previous = (x, y)


def _rect(pixels: bytearray, width: int, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
    for y in range(min(y1, y2), max(y1, y2) + 1):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            _set(pixels, width, x, y, color)


def _draw_centered_text(
    pixels: bytearray,
    width: int,
    center_x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    *,
    scale: int = 1,
) -> None:
    _draw_chart_text(pixels, width, center_x - _text_width(text, scale=scale) // 2, y, text, color, scale=scale)


def _draw_right_aligned_text(
    pixels: bytearray,
    width: int,
    right_x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    *,
    scale: int = 1,
) -> None:
    _draw_chart_text(pixels, width, right_x - _text_width(text, scale=scale), y, text, color, scale=scale)


def _draw_chart_text(
    pixels: bytearray,
    width: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    *,
    scale: int = 1,
) -> None:
    cursor = x
    for character in _normalize_text(text):
        glyph = FONT.get(character.upper(), FONT["?"])
        for row_index, row in enumerate(glyph):
            for col_index, enabled in enumerate(row):
                if enabled != "1":
                    continue
                _rect(
                    pixels,
                    width,
                    cursor + col_index * scale,
                    y + row_index * scale,
                    cursor + (col_index + 1) * scale - 1,
                    y + (row_index + 1) * scale - 1,
                    color,
                )
        cursor += 6 * scale


def _text_width(text: str, *, scale: int = 1) -> int:
    normalized = _normalize_text(text)
    if not normalized:
        return 0
    return (len(normalized) * 6 - 1) * scale


def _normalize_text(text: str) -> str:
    replacements = str.maketrans({"ä": "a", "ö": "o", "å": "a", "Ä": "A", "Ö": "O", "Å": "A", "–": "-", "—": "-"})
    return text.translate(replacements)


def _line(
    pixels: bytearray,
    width: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x2 - x1)
    dy = -abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    error = dx + dy
    x, y = x1, y1
    while True:
        _set(pixels, width, x, y, color)
        if x == x2 and y == y2:
            break
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x += sx
        if doubled <= dx:
            error += dx
            y += sy


def _stroke_line(
    pixels: bytearray,
    width: int,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int],
    *,
    stroke: int = 1,
) -> None:
    if stroke <= 1:
        _line(pixels, width, x1, y1, x2, y2, color)
        return
    radius = max(1, stroke // 2)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if abs(dx) + abs(dy) > radius:
                continue
            _line(pixels, width, x1 + dx, y1 + dy, x2 + dx, y2 + dy, color)


def _set(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0:
        return
    index = (y * width + x) * 3
    if index < 0 or index + 2 >= len(pixels):
        return
    pixels[index:index + 3] = bytes(color)


def _downsample(pixels: bytearray, width: int, height: int, *, scale: int) -> bytearray:
    source_width = width * scale
    output = bytearray()
    area = scale * scale
    for y in range(height):
        source_y = y * scale
        for x in range(width):
            source_x = x * scale
            red = green = blue = 0
            for dy in range(scale):
                row_start = ((source_y + dy) * source_width + source_x) * 3
                for dx in range(scale):
                    index = row_start + dx * 3
                    red += pixels[index]
                    green += pixels[index + 1]
                    blue += pixels[index + 2]
            output.extend((round(red / area), round(green / area), round(blue / area)))
    return output


def _png(width: int, height: int, pixels: bytearray) -> bytes:
    rows = bytearray()
    stride = width * 3
    for y in range(height):
        rows.append(0)
        start = y * stride
        rows.extend(pixels[start:start + stride])
    return PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + _chunk(
        b"IDAT",
        zlib.compress(bytes(rows), level=6),
    ) + _chunk(b"IEND", b"")


def _chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)


FONT = {
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
    "?": ("01110", "10001", "00001", "00010", "00100", "00000", "00100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    ",": ("00000", "00000", "00000", "00000", "00000", "01100", "01000"),
    ":": ("00000", "01100", "01100", "00000", "01100", "01100", "00000"),
    ";": ("00000", "01100", "01100", "00000", "01100", "01000", "10000"),
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "_": ("00000", "00000", "00000", "00000", "00000", "00000", "11111"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"),
    ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "%": ("11001", "11010", "00100", "01000", "10110", "00110", "00000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("01110", "00100", "00100", "00100", "00100", "00100", "01110"),
    "J": ("00001", "00001", "00001", "00001", "10001", "10001", "01110"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
}
