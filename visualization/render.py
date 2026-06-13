from __future__ import annotations

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


@dataclass(frozen=True)
class RenderSeries:
    metric: str
    values: tuple[float | None, ...]
    scaled: bool = False


@dataclass(frozen=True)
class LineChart:
    title: str
    x_values: tuple[float | None, ...]
    series: tuple[RenderSeries, ...]
    width: int = 900
    height: int = 520


@dataclass(frozen=True)
class Bar:
    label: str
    value: float


@dataclass(frozen=True)
class BarChart:
    title: str
    bars: tuple[Bar, ...]
    width: int = 900
    height: int = 520


def render_line_chart_png(chart: LineChart) -> bytes:
    pixels = _blank(chart.width, chart.height, (255, 255, 255))
    left, top, right, bottom = 70, 35, chart.width - 35, chart.height - 60
    _line(pixels, chart.width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, chart.width, left, top, left, bottom, (30, 30, 30))

    x_domain = _domain(chart.x_values)
    y_values = tuple(value for series in chart.series for value in series.values)
    y_domain = _domain(y_values)
    for index, series in enumerate(chart.series):
        color = COLORS[index % len(COLORS)]
        previous: tuple[int, int] | None = None
        for x_value, y_value in zip(chart.x_values, series.values, strict=False):
            if x_value is None or y_value is None:
                previous = None
                continue
            x = _scale(x_value, x_domain, left, right)
            y = _scale(y_value, y_domain, bottom, top)
            _dot(pixels, chart.width, x, y, color)
            if previous is not None:
                _line(pixels, chart.width, previous[0], previous[1], x, y, color)
            previous = (x, y)
    return _png(chart.width, chart.height, pixels)


def render_bar_chart_png(chart: BarChart) -> bytes:
    pixels = _blank(chart.width, chart.height, (255, 255, 255))
    left, top, right, bottom = 70, 35, chart.width - 35, chart.height - 60
    _line(pixels, chart.width, left, bottom, right, bottom, (30, 30, 30))
    _line(pixels, chart.width, left, top, left, bottom, (30, 30, 30))
    if not chart.bars:
        return _png(chart.width, chart.height, pixels)

    max_value = max((bar.value for bar in chart.bars), default=0.0)
    y_domain = (0.0, max(max_value, 1.0))
    slot_width = max(1, (right - left) // len(chart.bars))
    bar_width = max(8, round(slot_width * 0.65))
    for index, bar in enumerate(chart.bars):
        color = COLORS[index % len(COLORS)]
        center = left + index * slot_width + slot_width // 2
        x1 = center - bar_width // 2
        x2 = center + bar_width // 2
        y1 = _scale(bar.value, y_domain, bottom, top)
        _rect(pixels, chart.width, x1, y1, x2, bottom - 1, color)
    return _png(chart.width, chart.height, pixels)


def _blank(width: int, height: int, color: tuple[int, int, int]) -> bytearray:
    return bytearray(color * width * height)


def _domain(values: tuple[float | None, ...]) -> tuple[float, float]:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return (0.0, 1.0)
    low = min(numeric)
    high = max(numeric)
    if low == high:
        return (low - 1.0, high + 1.0)
    return (low, high)


def _scale(value: float, domain: tuple[float, float], low_px: int, high_px: int) -> int:
    low, high = domain
    ratio = (value - low) / (high - low)
    return round(low_px + ratio * (high_px - low_px))


def _dot(pixels: bytearray, width: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            _set(pixels, width, x + dx, y + dy, color)


def _rect(pixels: bytearray, width: int, x1: int, y1: int, x2: int, y2: int, color: tuple[int, int, int]) -> None:
    for y in range(min(y1, y2), max(y1, y2) + 1):
        for x in range(min(x1, x2), max(x1, x2) + 1):
            _set(pixels, width, x, y, color)


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
