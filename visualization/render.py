from __future__ import annotations

import math
from dataclasses import dataclass, field

from visualization.tiles import TileCoord


TILE_SIZE = 256
DEFAULT_RENDER_WIDTH = 1920
DEFAULT_RENDER_HEIGHT = 1080
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
    legend_title: str = "Legend"
    x_label: str = ""
    y_label: str = ""
    x_tick_format: str = "number"
    y_tick_format: str = "number"
    invert_y: bool = False
    width: int = DEFAULT_RENDER_WIDTH
    height: int = DEFAULT_RENDER_HEIGHT


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
    legend_title: str = "Legend"
    x_label: str = ""
    x_tick_format: str = "number"
    width: int = DEFAULT_RENDER_WIDTH
    height: int = DEFAULT_RENDER_HEIGHT


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
    legend_title: str = "Legend"
    x_label: str = ""
    y_label: str = ""
    y_tick_format: str = "number"
    width: int = DEFAULT_RENDER_WIDTH
    height: int = DEFAULT_RENDER_HEIGHT


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
    legend_title: str = "Legend"
    value_label: str = ""
    value_format: str = "number"
    width: int = DEFAULT_RENDER_WIDTH
    height: int = DEFAULT_RENDER_HEIGHT


@dataclass(frozen=True)
class RoutePoint:
    latitude: float
    longitude: float
    color_value: float | None = None


@dataclass(frozen=True)
class RoutePolyline:
    label: str
    points: tuple[RoutePoint, ...]
    color: tuple[int, int, int] | None = None
    color_metric: str = ""
    color_mode: str = "metric"


@dataclass(frozen=True)
class RouteWaypoint:
    latitude: float
    longitude: float
    label: str = ""
    waypoint_type: str = ""
    distance_km: float | None = None


@dataclass(frozen=True)
class RouteElevationSample:
    distance_km: float
    elevation_m: float
    grade: float = 0.0


@dataclass(frozen=True)
class RouteElevationProfile:
    samples: tuple[RouteElevationSample, ...]
    min_index: int
    max_index: int
    min_grade: float = 0.0
    max_grade: float = 0.0


@dataclass(frozen=True)
class RouteMapTile:
    coord: TileCoord
    content: bytes


@dataclass(frozen=True)
class RouteMap:
    title: str
    routes: tuple[RoutePolyline, ...]
    waypoints: tuple[RouteWaypoint, ...] = ()
    elevation_profile: RouteElevationProfile | None = None
    subtitle: str = ""
    legend_title: str = "Routes"
    color_metric_label: str = ""
    color_domain: tuple[float, float] | None = None
    color_tick_format: str = "number"
    color_direction: str = "ascending"
    color_mode: str = "metric"
    show_direction: bool = False
    tiles: tuple[RouteMapTile, ...] = ()
    tile_zoom: int | None = None
    tile_size: int = TILE_SIZE
    attribution: str = ""
    x_domain: tuple[float, float] | None = None
    y_domain: tuple[float, float] | None = None
    width: int = DEFAULT_RENDER_WIDTH
    height: int = DEFAULT_RENDER_HEIGHT


@dataclass(frozen=True)
class SocialImageStat:
    label: str
    value: str


@dataclass(frozen=True)
class SocialImageStyle:
    preset: str = ""
    background_crop: str = "center"
    background_dim: int = 30
    background_filter: str = "none"
    route_color: str = "default"
    route_size: str = "normal"
    route_shadow: bool = True
    route_markers: bool = True
    title_position: str = "top"
    title_align: str = "center"
    stats_position: str = "left"
    panel_style: str = "dark"
    text_color: str = "white"
    accent_color: str = "default"
    font: str = "clean"
    background_blur: int = 0
    route_position: str = "center"
    stats_style: str = "compact"


@dataclass(frozen=True)
class SocialImage:
    title: str
    routes: tuple[RoutePolyline, ...]
    stats: tuple[SocialImageStat, ...]
    background_image: bytes | None = None
    map_background: RouteMap | None = None
    style: SocialImageStyle = field(default_factory=SocialImageStyle)
    color_domain: tuple[float, float] | None = None
    color_direction: str = "ascending"
    width: int = 1080
    height: int = 1080


@dataclass(frozen=True)
class RouteMapViewport:
    x_domain: tuple[float, float]
    y_domain: tuple[float, float]


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


def route_map_viewport(
    routes: tuple[RoutePolyline, ...],
    *,
    waypoints: tuple[RouteWaypoint, ...] = (),
    width: int = DEFAULT_RENDER_WIDTH,
    height: int = DEFAULT_RENDER_HEIGHT,
    margin_ratio: float = 0.06,
    safe_rect: tuple[int, int, int, int] | None = None,
) -> RouteMapViewport:
    projected_points = tuple(
        _mercator_xy(point.latitude, point.longitude)
        for route in routes
        for point in route.points
    ) + tuple(_mercator_xy(waypoint.latitude, waypoint.longitude) for waypoint in waypoints)
    if not projected_points:
        return RouteMapViewport((0.0, 1.0), (0.0, 1.0))
    x_values = tuple(point[0] for point in projected_points)
    y_values = tuple(point[1] for point in projected_points)
    route_x = _padded_domain((min(x_values), max(x_values)), ratio=margin_ratio)
    route_y = _padded_domain((min(y_values), max(y_values)), ratio=margin_ratio)
    safe_left, safe_top, safe_right, safe_bottom = safe_rect or _best_route_safe_rect(route_x, route_y, width, height)
    return _route_map_viewport_for_rect(route_x, route_y, width, height, (safe_left, safe_top, safe_right, safe_bottom))


def _best_route_safe_rect(route_x: tuple[float, float], route_y: tuple[float, float], width: int, height: int) -> tuple[int, int, int, int]:
    candidates = (
        (48, 156, width - 48, height - 28),
        _route_safe_rect(width, height),
        (48, 156, width - 448, height - 28),
    )
    valid_candidates = tuple(rect for rect in candidates if rect[2] - rect[0] > 64 and rect[3] - rect[1] > 64)
    if not valid_candidates:
        return _route_safe_rect(width, height)
    return min(valid_candidates, key=lambda rect: _route_mercator_per_pixel(route_x, route_y, rect))


def _route_mercator_per_pixel(route_x: tuple[float, float], route_y: tuple[float, float], rect: tuple[int, int, int, int]) -> float:
    safe_left, safe_top, safe_right, safe_bottom = rect
    safe_width = max(1, safe_right - safe_left)
    safe_height = max(1, safe_bottom - safe_top)
    route_width = max(route_x[1] - route_x[0], 0.000001)
    route_height = max(route_y[1] - route_y[0], 0.000001)
    return max(route_width / safe_width, route_height / safe_height)


def _route_map_viewport_for_rect(
    route_x: tuple[float, float],
    route_y: tuple[float, float],
    width: int,
    height: int,
    rect: tuple[int, int, int, int],
) -> RouteMapViewport:
    safe_left, safe_top, safe_right, safe_bottom = rect
    mercator_per_pixel = _route_mercator_per_pixel(route_x, route_y, rect)
    domain_width = mercator_per_pixel * width
    domain_height = mercator_per_pixel * height
    route_center_x = (route_x[0] + route_x[1]) / 2.0
    route_center_y = (route_y[0] + route_y[1]) / 2.0
    safe_center_x = (safe_left + safe_right) / 2.0
    safe_center_y = (safe_top + safe_bottom) / 2.0
    x_low = route_center_x - (safe_center_x / width) * domain_width
    y_low = route_center_y - (safe_center_y / height) * domain_height
    x_domain = _clamped_domain(x_low, x_low + domain_width, 0.0, 1.0)
    y_domain = _clamped_domain(y_low, y_low + domain_height, 0.0, 1.0)
    return RouteMapViewport(x_domain, y_domain)


def _route_safe_rect(width: int, height: int) -> tuple[int, int, int, int]:
    return 48, 156, width - 448, height - 28


def route_metric_color(value: float, domain: tuple[float, float], *, direction: str = "ascending") -> tuple[int, int, int]:
    low, high = domain
    if high <= low:
        ratio = 0.5
    else:
        ratio = (value - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    if direction == "descending":
        ratio = 1.0 - ratio
    stops = (
        (37, 99, 235),
        (22, 163, 74),
        (234, 179, 8),
        (220, 38, 38),
    )
    scaled = ratio * (len(stops) - 1)
    index = min(int(scaled), len(stops) - 2)
    local = scaled - index
    return _lerp_color(stops[index], stops[index + 1], local)


def _mercator_xy(latitude: float, longitude: float) -> tuple[float, float]:
    clamped_latitude = max(min(latitude, 85.05112878), -85.05112878)
    lat_rad = math.radians(clamped_latitude)
    x = (longitude + 180.0) / 360.0
    y = (1.0 - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi) / 2.0
    return x, y


def _padded_domain(domain: tuple[float, float], *, ratio: float = 0.08) -> tuple[float, float]:
    low, high = domain
    if low == high:
        return low - 0.0001, high + 0.0001
    padding = (high - low) * ratio
    return low - padding, high + padding


def _clamped_domain(low: float, high: float, domain_low: float, domain_high: float) -> tuple[float, float]:
    span = high - low
    if span >= domain_high - domain_low:
        return domain_low, domain_high
    if low < domain_low:
        return domain_low, domain_low + span
    if high > domain_high:
        return domain_high - span, domain_high
    return low, high


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
