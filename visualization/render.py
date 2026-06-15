from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
COLORS = (
    (26, 95, 180),
    (210, 75, 65),
    (40, 145, 90),
    (145, 90, 180),
)
MARKER_POINT_LIMIT = 80


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


def render_line_chart_png(chart: LineChart) -> bytes:
    pixels = _background(chart.width, chart.height)
    left, top, right, bottom = 92, 92, chart.width - 34, chart.height - 72
    _draw_chart_text(pixels, chart.width, 24, 18, chart.title, (24, 24, 24), scale=2)
    if chart.subtitle:
        _draw_chart_text(pixels, chart.width, 24, 42, chart.subtitle, (90, 90, 90), scale=1)
    _line(pixels, chart.width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, chart.width, left, top, left, bottom, (30, 30, 30))

    x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
    y_values = tuple(value for series in chart.series for value in series.values)
    preliminary_y_axis = _robust_axis(y_values, target_ticks=6)
    render_series = tuple(_prepare_render_series(series, preliminary_y_axis) for series in chart.series)
    render_y_values = tuple(value for series in render_series for value in series.values)
    y_axis = _robust_axis(render_y_values, target_ticks=6)
    y_label = chart.y_label
    if len(render_series) == 1:
        y_label = _label_with_suffixes(y_label, render_series[0])
    _draw_x_axis(pixels, chart.width, left, right, bottom, x_axis, chart.x_label, tick_format=chart.x_tick_format)
    _draw_y_axis(
        pixels,
        chart.width,
        left,
        top,
        bottom,
        y_axis,
        y_label,
        tick_format=chart.y_tick_format,
        invert_y=chart.invert_y,
    )
    if len(render_series) > 1:
        _draw_legend(pixels, chart.width, render_series, right - 190, 18)
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
                _line(pixels, chart.width, previous[0], previous[1], x, y, color)
            if show_markers:
                _dot(pixels, chart.width, x, y, color)
            previous = (x, y)
    return _png(chart.width, chart.height, pixels)


def render_multi_panel_line_chart_png(chart: MultiPanelLineChart) -> bytes:
    pixels = _background(chart.width, chart.height)
    left, top, right, bottom = 92, 92, chart.width - 34, chart.height - 72
    _draw_chart_text(pixels, chart.width, 24, 18, chart.title, (24, 24, 24), scale=2)
    if chart.subtitle:
        _draw_chart_text(pixels, chart.width, 24, 42, chart.subtitle, (90, 90, 90), scale=1)
    if not chart.panels:
        return _png(chart.width, chart.height, pixels)

    x_axis = _time_axis(chart.x_values, target_ticks=6) if chart.x_tick_format == "duration" else _axis(chart.x_values, target_ticks=6)
    gap = 26
    panel_count = len(chart.panels)
    panel_height = max(72, (bottom - top - gap * (panel_count - 1)) // panel_count)
    for index, panel in enumerate(chart.panels):
        panel_top = top + index * (panel_height + gap)
        panel_bottom = panel_top + panel_height
        _line(pixels, chart.width, left, panel_bottom, right, panel_bottom, (30, 30, 30))
        _line(pixels, chart.width, left, panel_top, left, panel_bottom, (30, 30, 30))
        preliminary_y_axis = _robust_axis(panel.series.values, target_ticks=5)
        render_series = _prepare_render_series(panel.series, preliminary_y_axis)
        y_axis = _robust_axis(render_series.values, target_ticks=5)
        label = _label_with_suffixes(panel.y_label, render_series)
        _draw_y_axis(
            pixels,
            chart.width,
            left,
            panel_top,
            panel_bottom,
            y_axis,
            label,
            tick_format=panel.y_tick_format,
            invert_y=panel.invert_y,
        )
        _draw_panel_series(
            pixels,
            chart.width,
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
        )

    _draw_x_axis(
        pixels,
        chart.width,
        left,
        right,
        top + (panel_count - 1) * (panel_height + gap) + panel_height,
        x_axis,
        chart.x_label,
        tick_format=chart.x_tick_format,
    )
    return _png(chart.width, chart.height, pixels)


def render_bar_chart_png(chart: BarChart) -> bytes:
    pixels = _background(chart.width, chart.height)
    left, top, right, bottom = 92, 92, chart.width - 34, chart.height - 86
    _draw_chart_text(pixels, chart.width, 24, 18, chart.title, (24, 24, 24), scale=2)
    if chart.subtitle:
        _draw_chart_text(pixels, chart.width, 24, 42, chart.subtitle, (90, 90, 90), scale=1)
    _line(pixels, chart.width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, chart.width, left, top, left, bottom, (30, 30, 30))
    if not chart.bars:
        return _png(chart.width, chart.height, pixels)

    y_axis = _axis(tuple(bar.value for bar in chart.bars), target_ticks=6, include_zero=True)
    _draw_y_axis(pixels, chart.width, left, top, bottom, y_axis, chart.y_label, tick_format=chart.y_tick_format)
    if chart.x_label:
        _draw_centered_text(pixels, chart.width, (left + right) // 2, chart.height - 24, chart.x_label, (70, 70, 70))
    slot_width = max(1, (right - left) // len(chart.bars))
    bar_width = max(8, round(slot_width * 0.65))
    for index, bar in enumerate(chart.bars):
        color = COLORS[index % len(COLORS)]
        center = left + index * slot_width + slot_width // 2
        x1 = center - bar_width // 2
        x2 = center + bar_width // 2
        y1 = _scale(bar.value, y_axis.domain, bottom, top)
        _rect(pixels, chart.width, x1, y1, x2, bottom - 1, color)
        _draw_centered_text(pixels, chart.width, center, bottom + 12, _ellipsize(bar.label, 12), (70, 70, 70))
    return _png(chart.width, chart.height, pixels)


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
            _line(pixels, width, previous[0], previous[1], x, y, color)
        if show_markers:
            _dot(pixels, width, x, y, color)
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


def _blank(width: int, height: int, color: tuple[int, int, int]) -> bytearray:
    return bytearray(color * width * height)


def _background(width: int, height: int) -> bytearray:
    pixels = bytearray()
    top = (247, 250, 252)
    middle = (255, 255, 255)
    bottom = (244, 246, 248)
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
) -> None:
    for tick in axis.ticks:
        x = _scale(tick, axis.domain, left, right)
        _line(pixels, width, x, bottom, x, bottom + 5, (30, 30, 30))
        _draw_centered_text(pixels, width, x, bottom + 12, _format_tick(tick, tick_format=tick_format), (70, 70, 70))
    if label:
        _draw_centered_text(pixels, width, (left + right) // 2, bottom + 42, label, (70, 70, 70))


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
) -> None:
    for tick in axis.ticks:
        y = _scale_y(tick, axis.domain, bottom, top, invert=invert_y)
        _line(pixels, width, left - 5, y, left, y, (30, 30, 30))
        _line(pixels, width, left + 1, y, width - 34, y, (230, 230, 230))
        _draw_right_aligned_text(pixels, width, left - 10, y - 4, _format_tick(tick, tick_format=tick_format), (70, 70, 70))
    if label:
        _draw_chart_text(pixels, width, left, top - 18, label, (70, 70, 70), scale=1)


def _draw_legend(pixels: bytearray, width: int, series: tuple[RenderSeries, ...], x: int, y: int) -> None:
    for index, item in enumerate(series):
        yy = y + index * 14
        color = COLORS[index % len(COLORS)]
        _line(pixels, width, x, yy + 4, x + 16, yy + 4, color)
        label = item.label or item.metric
        suffixes = []
        if item.scaled:
            suffixes.append("scaled")
        if item.clipped:
            suffixes.append("clipped")
        if item.smoothed:
            suffixes.append("smoothed")
        if suffixes:
            label = f"{label} ({', '.join(suffixes)})"
        _draw_chart_text(pixels, width, x + 22, yy, _ellipsize(label, 22), (70, 70, 70), scale=1)


def _format_tick(value: float, *, tick_format: str = "number") -> str:
    if tick_format == "duration":
        return _format_seconds(value)
    if tick_format == "pace":
        return _format_pace(value)
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


def _dot(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            _set(pixels, width, x + dx, y + dy, color)


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


def _set(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if x < 0 or y < 0:
        return
    index = (y * width + x) * 3
    if index < 0 or index + 2 >= len(pixels):
        return
    pixels[index:index + 3] = bytes(color)


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
