from __future__ import annotations

import math
from functools import lru_cache
from importlib import resources
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
    SocialImage,
    SocialImageStat,
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
    route_map_viewport,
)


RENDER_SCALE = 2
ROUTE_OVERLAY_ROW_HEIGHT = 40
ROUTE_OVERLAY_SECTION_GAP = 14
ROUTE_OVERLAY_HEADING_HEIGHT = 40
ROUTE_OVERLAY_TOP_PADDING = 14
ROUTE_OVERLAY_BOTTOM_PADDING = 14
ELEVATION_OVERLAY_HEIGHT = 220
ELEVATION_OVERLAY_BOTTOM_MARGIN = 14
ELEVATION_LABEL_ROWS = 3
ROUTE_MARKER_RADIUS = 8


@dataclass(frozen=True)
class MapMarkerLabelSpec:
    text: str
    point: tuple[float, float]
    border_color: tuple[int, int, int]
    fill_color: tuple[int, int, int, int] = (255, 255, 255, 232)
    text_color: tuple[int, int, int] = TEXT
    required: bool = True


@dataclass(frozen=True)
class ElevationMarkerSpec:
    label: str
    elevation_m: float
    x: float
    priority: int
    distance_km: float
    preferred_side: str = "right"
    required: bool = True


@dataclass(frozen=True)
class ElevationMarkerLabel:
    spec: ElevationMarkerSpec
    text: str
    box: tuple[float, float, float, float]


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

            viewport = route_map_viewport(chart.routes, waypoints=chart.waypoints, width=width, height=height)
            x_domain, y_domain = viewport.x_domain, viewport.y_domain
        background = _route_background(chart, x_domain, y_domain, width * scale, height * scale)
        image = background.convert("RGBA")
        draw = ImageDraw.Draw(image, "RGBA")
        route_pixel_points: list[tuple[RoutePolyline, list[tuple[float, float]]]] = []
        for index, (route, points) in enumerate(projected_routes):
            color = COLORS[index % len(COLORS)]
            pixel_points = [
                (
                    _scale_float(x_value, x_domain, 0, width * scale - 1),
                    _scale_float(y_value, y_domain, 0, height * scale - 1),
                )
                for x_value, y_value in points
            ]
            route_pixel_points.append((route, pixel_points))
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
        km_label_specs: tuple[MapMarkerLabelSpec, ...] = ()
        if len(route_pixel_points) == 1:
            route, pixel_points = route_pixel_points[0]
            km_markers = _route_km_markers(route, pixel_points)
            _draw_km_markers(draw, km_markers, scale=scale)
            km_label_specs = _km_marker_label_specs(km_markers, scale=scale)
        waypoint_label_specs = _draw_waypoints(draw, chart, x_domain, y_domain, width * scale, height * scale, scale=scale)
        _draw_map_marker_labels(
            draw,
            waypoint_label_specs,
            km_label_specs,
            bounds=(4 * scale, 4 * scale, width * scale - 4 * scale, height * scale - 4 * scale),
            scale=scale,
        )
        _draw_image_frame(draw, image.width, image.height, scale=scale)
        _draw_route_overlays(image, image.width, image.height, chart, scale=scale)
        _draw_elevation_overlay(image, chart, scale=scale)
        if chart.attribution:
            _draw_attribution(draw, image.width, image.height, chart.attribution, scale=scale)
        return _png_bytes(_downsample(image, width, height))

    def render_social_image_png(self, chart: SocialImage) -> bytes:
        scale = RENDER_SCALE
        width, height = chart.width, chart.height
        image = _social_background(chart, width * scale, height * scale)
        draw = ImageDraw.Draw(image, "RGBA")
        _draw_social_routes(draw, chart, width * scale, height * scale, scale=scale)
        _draw_social_overlays(image, chart, scale=scale)
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


def _draw_waypoints(
    draw: ImageDraw.ImageDraw,
    chart: RouteMap,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    width: int,
    height: int,
    *,
    scale: int,
) -> tuple[MapMarkerLabelSpec, ...]:
    color = (124, 58, 237)
    label_specs: list[MapMarkerLabelSpec] = []
    for waypoint in chart.waypoints:
        waypoint_x, waypoint_y = _mercator_xy(waypoint.latitude, waypoint.longitude)
        point = (
            _scale_float(waypoint_x, x_domain, 0, width - 1),
            _scale_float(waypoint_y, y_domain, 0, height - 1),
        )
        _draw_waypoint_marker(draw, point, waypoint.waypoint_type, color, scale=scale)
        label = _ellipsize(waypoint.label.strip(), 32)
        if not label:
            continue
        label_specs.append(
            MapMarkerLabelSpec(
                text=label,
                point=point,
                border_color=color,
                required=True,
            )
        )
    return tuple(label_specs)


def _route_km_markers(
    route: RoutePolyline,
    pixel_points: list[tuple[float, float]],
) -> tuple[tuple[float, tuple[float, float]], ...]:
    distances = _route_distances_for_pixels(route)
    if len(distances) != len(pixel_points) or len(distances) < 2:
        return ()
    distance_max = distances[-1]
    if distance_max <= 0:
        return ()
    step = _distance_tick_step(distance_max)
    markers: list[tuple[float, tuple[float, float]]] = []
    value = step
    while value < distance_max - 0.001:
        point = _point_at_route_distance(value, distances, pixel_points)
        if point is not None:
            markers.append((value, point))
        value += step
    return tuple(markers)


def _route_distances_for_pixels(route: RoutePolyline) -> tuple[float, ...]:
    if len(route.points) < 2:
        return ()
    distances = [0.0]
    for current, following in zip(route.points, route.points[1:], strict=False):
        distances.append(distances[-1] + _haversine_km(current.latitude, current.longitude, following.latitude, following.longitude))
    return tuple(distances)


def _point_at_route_distance(
    distance_km: float,
    distances: tuple[float, ...],
    pixel_points: list[tuple[float, float]],
) -> tuple[float, float] | None:
    if distance_km <= distances[0]:
        return pixel_points[0]
    if distance_km >= distances[-1]:
        return pixel_points[-1]
    for index, (left_distance, right_distance) in enumerate(zip(distances, distances[1:], strict=False)):
        if left_distance <= distance_km <= right_distance:
            span = max(right_distance - left_distance, 0.000001)
            ratio = (distance_km - left_distance) / span
            left_point = pixel_points[index]
            right_point = pixel_points[index + 1]
            return (
                left_point[0] + (right_point[0] - left_point[0]) * ratio,
                left_point[1] + (right_point[1] - left_point[1]) * ratio,
            )
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def _draw_km_markers(
    draw: ImageDraw.ImageDraw,
    markers: tuple[tuple[float, tuple[float, float]], ...],
    *,
    scale: int,
) -> None:
    for _, point in markers:
        _draw_marker(draw, point, (59, 130, 246), scale=scale)


def _km_marker_label_specs(
    markers: tuple[tuple[float, tuple[float, float]], ...],
    *,
    scale: int,
) -> tuple[MapMarkerLabelSpec, ...]:
    del scale
    return tuple(
        MapMarkerLabelSpec(
            text=f"{distance_km:.0f} km",
            point=point,
            border_color=(59, 130, 246),
            fill_color=(37, 99, 235, 232),
            text_color=(255, 255, 255),
            required=False,
        )
        for distance_km, point in markers
    )


def _draw_map_marker_labels(
    draw: ImageDraw.ImageDraw,
    waypoint_specs: tuple[MapMarkerLabelSpec, ...],
    km_specs: tuple[MapMarkerLabelSpec, ...],
    *,
    bounds: tuple[float, float, float, float],
    scale: int,
) -> None:
    occupied: list[tuple[float, float, float, float]] = []
    for spec in waypoint_specs:
        box = _place_map_marker_label(draw, spec, bounds=bounds, occupied=occupied, scale=scale)
        if box is None:
            continue
        occupied.append(box)
        _draw_map_label_box(
            draw,
            box[0],
            box[1],
            spec.text,
            scale=scale,
            border_color=spec.border_color,
            fill_color=spec.fill_color,
            text_color=spec.text_color,
        )
    for spec in km_specs:
        box = _place_map_marker_label(draw, spec, bounds=bounds, occupied=occupied, scale=scale)
        if box is None:
            continue
        occupied.append(box)
        _draw_map_label_box(
            draw,
            box[0],
            box[1],
            spec.text,
            scale=scale,
            border_color=spec.border_color,
            fill_color=spec.fill_color,
            text_color=spec.text_color,
        )


def _place_map_marker_label(
    draw: ImageDraw.ImageDraw,
    spec: MapMarkerLabelSpec,
    *,
    bounds: tuple[float, float, float, float],
    occupied: list[tuple[float, float, float, float]],
    scale: int,
) -> tuple[float, float, float, float] | None:
    for placement in ("right_up", "right_down", "left_up", "left_down"):
        box = _map_marker_label_box(draw, spec, placement, bounds=bounds, scale=scale)
        if box is None:
            continue
        if any(_boxes_overlap(box, existing, padding=3 * scale) for existing in occupied):
            continue
        return box
    if not spec.required:
        return None
    return _map_marker_label_box(draw, spec, "right_up", bounds=bounds, scale=scale, clamp=True)


def _map_marker_label_box(
    draw: ImageDraw.ImageDraw,
    spec: MapMarkerLabelSpec,
    placement: str,
    *,
    bounds: tuple[float, float, float, float],
    scale: int,
    clamp: bool = False,
) -> tuple[float, float, float, float] | None:
    font = _font(10 * scale, bold=True)
    box_width, box_height = _map_label_size(draw, spec.text, font=font, scale=scale)
    gap = 7 * scale
    anchor_x, anchor_y = spec.point
    if placement.startswith("left"):
        x = anchor_x - gap - box_width
    else:
        x = anchor_x + gap
    if placement.endswith("down"):
        y = anchor_y + gap
    else:
        y = anchor_y - gap - box_height
    min_x, min_y, max_x, max_y = bounds
    if clamp:
        x = min(max(x, min_x), max_x - box_width)
        y = min(max(y, min_y), max_y - box_height)
    elif x < min_x or x + box_width > max_x or y < min_y or y + box_height > max_y:
        return None
    return (x, y, x + box_width, y + box_height)


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


def _social_background(chart: SocialImage, width: int, height: int) -> Image.Image:
    if chart.background_image:
        try:
            with Image.open(BytesIO(chart.background_image)) as source:
                image = _cover_resize(source.convert("RGB"), width, height, crop=chart.style.background_crop)
                return _apply_social_background_style(image, chart)
        except OSError:
            pass
    if chart.map_background is not None:
        route_map = chart.map_background
        if route_map.x_domain is not None and route_map.y_domain is not None:
            x_domain, y_domain = route_map.x_domain, route_map.y_domain
        else:
            viewport = route_map_viewport(route_map.routes, width=chart.width, height=chart.height)
            x_domain, y_domain = viewport.x_domain, viewport.y_domain
        return _apply_social_background_style(_route_background(route_map, x_domain, y_domain, width, height), chart)
    return _apply_social_background_style(_background_image(width, height), chart)


def _apply_social_background_style(image: Image.Image, chart: SocialImage) -> Image.Image:
    styled = _apply_social_filter(image.convert("RGB"), chart.style.background_filter)
    if chart.style.background_blur > 0:
        styled = styled.filter(ImageFilter.GaussianBlur(radius=chart.style.background_blur))
    output = styled.convert("RGBA")
    dim_alpha = round(max(0, min(70, chart.style.background_dim)) / 100 * 255)
    if dim_alpha:
        dim = Image.new("RGBA", output.size, (0, 0, 0, dim_alpha))
        output.alpha_composite(dim)
    return output


def _cover_resize(source: Image.Image, width: int, height: int, *, crop: str = "center") -> Image.Image:
    source_width, source_height = source.size
    target_ratio = width / max(height, 1)
    source_ratio = source_width / max(source_height, 1)
    if source_ratio > target_ratio:
        crop_width = round(source_height * target_ratio)
        left = _crop_left(source_width, crop_width, crop)
        box = (left, 0, left + crop_width, source_height)
    else:
        crop_height = round(source_width / target_ratio)
        top = _crop_top(source_height, crop_height, crop)
        box = (0, top, source_width, top + crop_height)
    return source.crop(box).resize((width, height), Image.Resampling.LANCZOS)


def _crop_left(source_width: int, crop_width: int, crop: str) -> int:
    crop = crop.strip().lower()
    if crop == "left":
        return 0
    if crop == "right":
        return max(0, source_width - crop_width)
    point = _crop_point(crop)
    if point is not None:
        return max(0, min(source_width - crop_width, round(source_width * point[0] - crop_width / 2)))
    return max(0, (source_width - crop_width) // 2)


def _crop_top(source_height: int, crop_height: int, crop: str) -> int:
    crop = crop.strip().lower()
    if crop == "top":
        return 0
    if crop == "bottom":
        return max(0, source_height - crop_height)
    point = _crop_point(crop)
    if point is not None:
        return max(0, min(source_height - crop_height, round(source_height * point[1] - crop_height / 2)))
    return max(0, (source_height - crop_height) // 2)


def _crop_point(crop: str) -> tuple[float, float] | None:
    parts = crop.split(",", 1)
    if len(parts) != 2:
        return None
    try:
        x_value = max(0, min(100, int(parts[0]))) / 100
        y_value = max(0, min(100, int(parts[1]))) / 100
    except ValueError:
        return None
    return x_value, y_value


def _apply_social_filter(image: Image.Image, value: str) -> Image.Image:
    mode = value.strip().lower()
    if mode in {"", "none"}:
        return image
    if mode == "bw":
        return image.convert("L").convert("RGB")
    pixels = image.convert("RGB")
    overlay_color = {
        "warm": (255, 170, 80),
        "cool": (70, 125, 255),
        "vivid": (255, 255, 255),
        "matte": (180, 170, 150),
    }.get(mode)
    if overlay_color is None:
        return image
    overlay = Image.new("RGB", pixels.size, overlay_color)
    alpha = {"warm": 0.12, "cool": 0.12, "vivid": 0.08, "matte": 0.16}[mode]
    blended = Image.blend(pixels, overlay, alpha)
    if mode == "vivid":
        return Image.blend(blended, pixels.point(lambda p: min(255, round(p * 1.08))), 0.55)
    return blended


def _draw_social_routes(draw: ImageDraw.ImageDraw, chart: SocialImage, width: int, height: int, *, scale: int) -> None:
    for route in chart.routes:
        points = _social_route_points(chart, route, width, height, scale=scale)
        if len(points) < 2:
            continue
        size_factor = _social_route_size_factor(chart.style.route_size)
        line_width = max(5 * scale, round(min(width, height) * 0.009 * size_factor))
        route_color = _social_color(chart.style.route_color, default=(37, 99, 235))
        if chart.style.route_shadow:
            _draw_social_polyline(draw, points, (0, 0, 0, 179), width=line_width)
        offset_points = _offset_points(points, 3 * scale, 3 * scale)
        if chart.color_domain is not None and route.color_metric:
            _draw_social_colored_polyline(
                draw,
                route,
                offset_points,
                chart.color_domain,
                fallback=route_color,
                direction=chart.color_direction,
                width=line_width,
            )
        else:
            _draw_social_polyline(draw, offset_points, route_color + (255,), width=line_width)
        if chart.style.route_markers:
            _draw_marker(draw, points[0], (22, 163, 74), scale=scale)
            _draw_marker(draw, points[-1], (220, 38, 38), scale=scale)


def _draw_social_polyline(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    color: tuple[int, int, int, int],
    *,
    width: int,
) -> None:
    radius = width / 2.0
    for current, following in zip(points, points[1:], strict=False):
        draw.line((current, following), fill=color, width=width)
        _draw_route_joint_rgba(draw, current, radius, color)
        _draw_route_joint_rgba(draw, following, radius, color)


def _draw_social_colored_polyline(
    draw: ImageDraw.ImageDraw,
    route: RoutePolyline,
    points: list[tuple[float, float]],
    color_domain: tuple[float, float],
    *,
    fallback: tuple[int, int, int],
    direction: str,
    width: int,
) -> None:
    radius = width / 2.0
    for index, (current, following) in enumerate(zip(points, points[1:], strict=False)):
        first = route.points[index].color_value
        second = route.points[index + 1].color_value
        if first is not None:
            color = route_metric_color(first, color_domain, direction=direction)
        elif second is not None:
            color = route_metric_color(second, color_domain, direction=direction)
        else:
            color = fallback
        rgba = color + (255,)
        draw.line((current, following), fill=rgba, width=width)
        _draw_route_joint_rgba(draw, current, radius, rgba)
        _draw_route_joint_rgba(draw, following, radius, rgba)


def _draw_route_joint_rgba(
    draw: ImageDraw.ImageDraw,
    point: tuple[float, float],
    radius: float,
    color: tuple[int, int, int, int],
) -> None:
    x, y = point
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)


def _offset_points(points: list[tuple[float, float]], dx: float, dy: float) -> list[tuple[float, float]]:
    return [(x + dx, y + dy) for x, y in points]


def _social_route_points(
    chart: SocialImage,
    route: RoutePolyline,
    width: int,
    height: int,
    *,
    scale: int,
) -> list[tuple[float, float]]:
    projected = tuple(_mercator_xy(point.latitude, point.longitude) for point in route.points)
    if not projected:
        return []
    if chart.background_image or chart.map_background is None:
        return _decorative_route_points(projected, width, height, scale=scale, position=chart.style.route_position)
    route_map = chart.map_background
    if route_map.x_domain is not None and route_map.y_domain is not None:
        x_domain, y_domain = route_map.x_domain, route_map.y_domain
    else:
        viewport = route_map_viewport(route_map.routes, width=chart.width, height=chart.height)
        x_domain, y_domain = viewport.x_domain, viewport.y_domain
    return [
        (
            _scale_float(x_value, x_domain, 0, width - 1),
            _scale_float(y_value, y_domain, 0, height - 1),
        )
        for x_value, y_value in projected
    ]


def _decorative_route_points(
    points: tuple[tuple[float, float], ...],
    width: int,
    height: int,
    *,
    scale: int,
    position: str = "center",
) -> list[tuple[float, float]]:
    x_values = tuple(point[0] for point in points)
    y_values = tuple(point[1] for point in points)
    x_domain = (min(x_values), max(x_values))
    y_domain = (min(y_values), max(y_values))
    route_ratio = (x_domain[1] - x_domain[0]) / max(y_domain[1] - y_domain[0], 1e-9)
    available_width = width * 0.78
    available_height = height * 0.62
    if route_ratio >= available_width / max(available_height, 1):
        route_width = available_width
        route_height = route_width / max(route_ratio, 1e-9)
    else:
        route_height = available_height
        route_width = route_height * route_ratio
    route_width = max(width * 0.54, min(route_width, width * 0.86))
    route_height = max(height * 0.34, min(route_height, height * 0.70))
    left = (width - route_width) / 2.0
    top = (height - route_height) / 2.0 + height * 0.05
    position = position.strip().lower()
    if position == "top":
        top = height * 0.18
    elif position == "bottom":
        top = height - route_height - height * 0.12
    elif position == "left":
        left = width * 0.08
    elif position == "right":
        left = width - route_width - width * 0.08
    right = left + route_width
    bottom = top + route_height
    return [
        (
            _scale_float(x_value, x_domain, left, right),
            _scale_float(y_value, y_domain, top, bottom),
        )
        for x_value, y_value in points
    ]


def _draw_social_overlays(image: Image.Image, chart: SocialImage, *, scale: int) -> None:
    if chart.style.title_position == "hide" and chart.style.stats_position == "hide":
        return
    panel_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel_layer, "RGBA")
    overlay_scale = 2 * scale
    padding = 20 * scale
    title_left = 22 * scale
    title_width = image.width - 44 * scale
    title_font = _social_font(24 * overlay_scale, chart.style.font, bold=True)
    title_text_width = title_width - 2 * padding
    title_lines = _wrap_text(panel_draw, chart.title, title_text_width, title_font, max_lines=2)
    title_height = padding * 2 + len(title_lines) * 48 * scale
    title_top = 22 * scale if chart.style.title_position != "bottom" else image.height - title_height - 22 * scale
    if chart.style.title_position != "hide":
        _social_panel(panel_draw, (title_left, title_top, title_left + title_width, title_top + title_height), chart.style.panel_style)
    stats_box = _social_stats_box(
        image.width,
        image.height,
        chart.stats,
        scale=scale,
        position=chart.style.stats_position,
        stats_style=chart.style.stats_style,
    )
    if stats_box is not None:
        _social_panel(panel_draw, stats_box, chart.style.panel_style)
    image.alpha_composite(panel_layer)
    draw = ImageDraw.Draw(image, "RGBA")
    text = _social_text_color(chart.style.text_color)
    muted = _social_muted_color(text)
    if chart.style.title_position != "hide":
        for index, line in enumerate(title_lines):
            y = title_top + padding + index * 48 * scale
            if chart.style.title_align == "left":
                _draw_text(draw, title_left + padding, y, line, text, title_font)
            else:
                _draw_text_center(draw, image.width // 2, y, line, text, title_font)
    if stats_box is not None:
        _draw_social_stats(draw, stats_box, chart.stats, text, muted, chart.style.font, chart.style.stats_style, scale=scale)


def _social_stats_box(
    width: int,
    height: int,
    stats: tuple[SocialImageStat, ...],
    *,
    scale: int,
    position: str = "left",
    stats_style: str = "compact",
) -> tuple[int, int, int, int] | None:
    if not stats or position == "hide":
        return None
    padding = 18 * scale
    box_width = min(520 * scale if position == "bottom" else 460 * scale, width - 44 * scale)
    row_height = (64 if stats_style in {"large", "stacked"} else 48) * scale
    box_height = padding * 2 + row_height * min(len(stats), 4)
    if position == "right":
        left = width - box_width - 22 * scale
    elif position == "bottom":
        left = (width - box_width) // 2
    else:
        left = 22 * scale
    bottom = height - 22 * scale
    return (left, bottom - box_height, left + box_width, bottom)


def _draw_social_stats(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    stats: tuple[SocialImageStat, ...],
    text: tuple[int, int, int],
    muted: tuple[int, int, int],
    font_family: str,
    stats_style: str,
    *,
    scale: int,
) -> None:
    overlay_scale = 2 * scale
    padding = 18 * scale
    row_height = 58 * scale if stats_style == "large" else 48 * scale
    x = box[0] + padding
    y = box[1] + padding
    value_x = box[2] - padding
    label_font = _social_font(10 * overlay_scale, font_family, bold=True)
    value_font = _social_font((20 if stats_style == "large" else 16) * overlay_scale, font_family, bold=True)
    for stat in stats[:4]:
        label_height = _text_size(draw, stat.label, label_font)[1]
        value_height = _text_size(draw, stat.value, value_font)[1]
        row_center = y + row_height / 2.0
        if stats_style == "stacked":
            _draw_text(draw, x, round(y), stat.label, muted, label_font)
            _draw_text(draw, x, round(y + label_height + 4 * scale), stat.value, text, value_font)
        else:
            _draw_text(draw, x, round(row_center - label_height / 2.0), stat.label, muted, label_font)
            _draw_text_right(draw, value_x, round(row_center - value_height / 2.0), stat.value, text, value_font)
        y += row_height


def _social_route_size_factor(value: str) -> float:
    return {
        "small": 0.72,
        "normal": 1.0,
        "large": 1.35,
        "huge": 1.75,
    }.get(value.strip().lower(), 1.0)


def _social_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], style: str) -> None:
    mode = style.strip().lower()
    if mode == "none":
        return
    if mode == "light":
        draw.rounded_rectangle(box, radius=0, fill=(248, 250, 252, 205), outline=(226, 232, 240, 120), width=1)
        return
    _dark_panel(draw, box)


def _social_color(value: str, *, default: tuple[int, int, int]) -> tuple[int, int, int]:
    text = value.strip().lower()
    if text in {"", "default", "auto"}:
        return default
    named = {
        "blue": (37, 99, 235),
        "white": (255, 255, 255),
        "black": (15, 23, 42),
        "red": (220, 38, 38),
        "green": (22, 163, 74),
        "yellow": (250, 204, 21),
    }.get(text)
    if named is not None:
        return named
    if len(text) == 7 and text.startswith("#"):
        try:
            return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
        except ValueError:
            return default
    return default


def _social_text_color(value: str) -> tuple[int, int, int]:
    text = value.strip().lower()
    if text == "black":
        return (15, 23, 42)
    if len(text) == 7 and text.startswith("#"):
        return _social_color(text, default=(255, 255, 255))
    return (255, 255, 255)


def _social_muted_color(text: tuple[int, int, int]) -> tuple[int, int, int]:
    if sum(text) < 200:
        return (71, 85, 105)
    return (226, 232, 240)


def _social_font(size: int, family: str, *, bold: bool = False) -> ImageFont.ImageFont:
    normalized = family.strip().lower()
    if normalized == "mono":
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        )
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=max(8, size))
            except OSError:
                continue
    if normalized == "serif":
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
        )
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=max(8, size))
            except OSError:
                continue
    return _font(size, bold=bold or normalized == "bold")


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
        visible_waypoint_count = _visible_waypoint_count(len(chart.waypoints), height, visible_route_count, scale=scale)
        overlay_height = _route_overlay_height(
            color_scale_only=color_scale_only,
            visible_route_count=visible_route_count,
            visible_waypoint_count=visible_waypoint_count,
            scale=scale,
        )
        left = width - overlay_width - 14 * scale
        top = 12 * scale
        if overlay_height > 0:
            _dark_panel(panel_draw, (left, top, width - 14 * scale, top + min(overlay_height, height - 24 * scale)))
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
    visible_waypoint_count = _visible_waypoint_count(len(chart.waypoints), height, visible_route_count, scale=scale)
    left = width - overlay_width - 14 * scale
    top = 12 * scale
    if color_scale_only:
        _draw_route_color_scale(draw, left + padding, top + 10 * scale, chart, route_text, route_muted_text, scale=scale)
        return
    y = top + ROUTE_OVERLAY_TOP_PADDING * scale
    if visible_route_count:
        _draw_route_overlay_heading(draw, left + padding, y, chart.legend_title, route_text, scale=scale)
        y += ROUTE_OVERLAY_HEADING_HEIGHT * scale
    for index, route in enumerate(chart.routes[:visible_route_count]):
        color = route.color or COLORS[index % len(COLORS)]
        draw.line((left + padding, y + 13 * scale, left + padding + 36 * scale, y + 13 * scale), fill=color, width=max(12, 6 * scale))
        _draw_text(draw, left + padding + 52 * scale, y - 1 * scale, _ellipsize(route.label, 28), route_text, _font(10 * overlay_scale))
        y += ROUTE_OVERLAY_ROW_HEIGHT * scale
    if visible_route_count and len(chart.routes) > visible_route_count:
        _draw_text(draw, left + padding + 52 * scale, y - 1 * scale, "...", route_muted_text, _font(10 * overlay_scale))
        y += ROUTE_OVERLAY_ROW_HEIGHT * scale
    if visible_route_count and visible_waypoint_count:
        y += ROUTE_OVERLAY_SECTION_GAP * scale
    _draw_waypoint_overlay_list(
        draw,
        chart.waypoints[:visible_waypoint_count],
        hidden_count=max(0, len(chart.waypoints) - visible_waypoint_count),
        left=left + padding,
        top=y,
        width=overlay_width - 2 * padding,
        text=route_text,
        muted=route_muted_text,
        scale=scale,
    )


def _visible_route_legend_count(route_count: int, height: int, *, scale: int) -> int:
    if route_count <= 1:
        return 0
    available_rows = max(1, (height - 108 * scale) // (ROUTE_OVERLAY_ROW_HEIGHT * scale))
    return min(route_count, 20, available_rows)


def _visible_waypoint_count(waypoint_count: int, height: int, route_count: int, *, scale: int) -> int:
    if waypoint_count <= 0:
        return 0
    used = (
        ROUTE_OVERLAY_TOP_PADDING * scale
        + (ROUTE_OVERLAY_HEADING_HEIGHT + route_count * ROUTE_OVERLAY_ROW_HEIGHT) * scale
        + (ROUTE_OVERLAY_SECTION_GAP * scale if route_count else 0)
        + ROUTE_OVERLAY_HEADING_HEIGHT * scale
        + ROUTE_OVERLAY_BOTTOM_PADDING * scale
    )
    available_rows = max(0, (height - used - 24 * scale) // (ROUTE_OVERLAY_ROW_HEIGHT * scale))
    return min(waypoint_count, 12, available_rows)


def _waypoint_overlay_height(visible_count: int, *, scale: int) -> int:
    if visible_count <= 0:
        return 0
    return (ROUTE_OVERLAY_HEADING_HEIGHT + visible_count * ROUTE_OVERLAY_ROW_HEIGHT) * scale


def _route_overlay_height(
    *,
    color_scale_only: bool,
    visible_route_count: int,
    visible_waypoint_count: int,
    scale: int,
) -> int:
    if color_scale_only:
        return 86 * scale
    if visible_route_count <= 0 and visible_waypoint_count <= 0:
        return 0
    height = ROUTE_OVERLAY_TOP_PADDING * scale + ROUTE_OVERLAY_BOTTOM_PADDING * scale
    if visible_route_count:
        height += (ROUTE_OVERLAY_HEADING_HEIGHT + visible_route_count * ROUTE_OVERLAY_ROW_HEIGHT) * scale
    if visible_waypoint_count:
        if visible_route_count:
            height += ROUTE_OVERLAY_SECTION_GAP * scale
        height += _waypoint_overlay_height(visible_waypoint_count, scale=scale)
    return height


def _draw_waypoint_overlay_list(
    draw: ImageDraw.ImageDraw,
    waypoints,
    *,
    hidden_count: int,
    left: int,
    top: int,
    width: int,
    text: tuple[int, int, int],
    muted: tuple[int, int, int],
    scale: int,
) -> None:
    if not waypoints:
        return
    overlay_scale = 2 * scale
    row_font = _font(10 * overlay_scale)
    distance_font = row_font
    icon_column = 42 * scale
    distance_column = 74 * scale
    _draw_route_overlay_heading(draw, left, top, "Reittimerkit", text, scale=scale)
    y = top + ROUTE_OVERLAY_HEADING_HEIGHT * scale
    distance_x = left + width
    for waypoint in waypoints:
        _draw_waypoint_overlay_marker(draw, (left + 10 * scale, y + 14 * scale), waypoint.waypoint_type, (124, 58, 237), scale=scale)
        label = _ellipsize_to_width(draw, waypoint.label or "Reittimerkki", max(40 * scale, width - icon_column - distance_column), row_font)
        _draw_text(draw, left + icon_column, y - 1 * scale, label, text, row_font)
        if waypoint.distance_km is not None:
            _draw_text_right(draw, distance_x, y - 1 * scale, f"{waypoint.distance_km:.1f} km", muted, distance_font)
        y += ROUTE_OVERLAY_ROW_HEIGHT * scale
    if hidden_count > 0:
        _draw_text(draw, left + icon_column, y - 1 * scale, f"+{hidden_count}", muted, row_font)


def _draw_route_overlay_heading(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    text: str,
    color: tuple[int, int, int],
    *,
    scale: int,
) -> None:
    _draw_text(draw, left, top, text, color, _font(12 * 2 * scale, bold=True))


def _draw_waypoint_overlay_marker(
    draw: ImageDraw.ImageDraw,
    point: tuple[float, float],
    waypoint_type: str,
    color: tuple[int, int, int],
    *,
    scale: int,
) -> None:
    x, y = point
    icon_color = _waypoint_color(waypoint_type) or color
    radius = 10 * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 242), outline=icon_color + (255,), width=2 * scale)
    icon_font = _waypoint_icon_font(9 * scale)
    icon = _waypoint_icon_text(waypoint_type)
    if icon_font is not None:
        text_width, text_height = _text_size(draw, icon, icon_font)
        _draw_text(draw, round(x - text_width / 2), round(y - text_height / 2), icon, icon_color, icon_font)
        return
    fallback = _waypoint_fallback_icon(waypoint_type)
    font = _font(9 * scale, bold=True)
    text_width, text_height = _text_size(draw, fallback, font)
    _draw_text(draw, round(x - text_width / 2), round(y - text_height / 2), fallback, icon_color, font)


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


def _draw_elevation_overlay(image: Image.Image, chart: RouteMap, *, scale: int) -> None:
    profile = chart.elevation_profile
    if profile is None or len(profile.samples) < 3:
        return
    width, height = image.width, image.height
    margin_x = 14 * scale
    bottom_margin = ELEVATION_OVERLAY_BOTTOM_MARGIN * scale
    panel_height = ELEVATION_OVERLAY_HEIGHT * scale
    left = margin_x
    right = width - margin_x
    bottom = height - bottom_margin
    top = bottom - panel_height
    panel_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel_layer, "RGBA")
    _dark_panel(panel_draw, (left, top, right, bottom))
    image.alpha_composite(panel_layer)
    draw = ImageDraw.Draw(image, "RGBA")

    padding_x = 28 * scale
    padding_y = 16 * scale
    plot_left = left + padding_x
    plot_right = right - padding_x
    elevations = tuple(sample.elevation_m for sample in profile.samples)
    min_elevation = min(elevations)
    max_elevation = max(elevations)
    distance_max = max(sample.distance_km for sample in profile.samples)
    if distance_max <= 0 or max_elevation - min_elevation < 1:
        return
    grade_scale_box = _grade_scale_box(plot_right - 285 * scale, top + 12 * scale, scale=scale)
    label_band_top = grade_scale_box[3] + 8 * scale
    label_band_bottom = label_band_top + _elevation_label_row_height(draw, scale=scale) * ELEVATION_LABEL_ROWS
    preliminary_points = _elevation_profile_points(
        profile,
        distance_max=distance_max,
        y_domain=(min_elevation, max_elevation),
        plot_left=plot_left,
        plot_right=plot_right,
        plot_top=0,
        plot_bottom=1,
    )
    marker_specs = _elevation_marker_specs(profile, chart, preliminary_points)
    marker_labels = _layout_elevation_marker_labels(
        draw,
        marker_specs,
        label_bounds=(left + 6 * scale, label_band_top, right - 6 * scale, label_band_bottom),
        scale=scale,
    )
    used_label_rows = _used_elevation_label_rows(marker_labels, label_band_top, draw, scale=scale)
    label_area_bottom = label_band_top + max(1, used_label_rows) * _elevation_label_row_height(draw, scale=scale)
    axis_height = 24 * scale
    plot_top = label_area_bottom + 10 * scale
    plot_bottom = bottom - padding_y - axis_height
    y_domain = _padded_elevation_domain(min_elevation, max_elevation)
    points = _elevation_profile_points(
        profile,
        distance_max=distance_max,
        y_domain=y_domain,
        plot_left=plot_left,
        plot_right=plot_right,
        plot_top=plot_top,
        plot_bottom=plot_bottom,
    )
    baseline = plot_bottom
    for index, (current, following) in enumerate(zip(points, points[1:], strict=False)):
        _draw_elevation_gradient_segment(
            draw,
            current,
            following,
            baseline,
            profile.samples[index].grade,
            profile.samples[index + 1].grade,
            scale=scale,
        )
    marker_specs = _elevation_marker_specs(profile, chart, points)
    marker_labels = _layout_elevation_marker_labels(
        draw,
        marker_specs,
        label_bounds=(left + 6 * scale, label_band_top, right - 6 * scale, label_band_bottom),
        scale=scale,
    )
    for marker in marker_labels:
        _draw_elevation_marker(draw, marker, plot_top, plot_bottom, scale=scale)
    _draw_grade_scale(draw, profile, grade_scale_box[0], grade_scale_box[1], scale=scale)
    _draw_elevation_distance_axis(draw, distance_max, plot_left, plot_right, plot_bottom + 9 * scale, scale=scale)


def _draw_elevation_gradient_segment(
    draw: ImageDraw.ImageDraw,
    current: tuple[float, float],
    following: tuple[float, float],
    baseline: int,
    start_grade: float,
    end_grade: float,
    *,
    scale: int,
) -> None:
    segment_width = abs(following[0] - current[0])
    steps = max(1, min(12, round(segment_width / max(4 * scale, 1))))
    previous = current
    for step in range(1, steps + 1):
        ratio = step / steps
        point = (
            current[0] + (following[0] - current[0]) * ratio,
            current[1] + (following[1] - current[1]) * ratio,
        )
        grade = start_grade + (end_grade - start_grade) * (ratio - 0.5 / steps)
        color = _grade_color(grade)
        polygon = (previous, point, (point[0], baseline), (previous[0], baseline))
        draw.polygon(polygon, fill=color + (52,))
        draw.line((previous, point), fill=color + (255,), width=max(2, 2 * scale))
        previous = point


def _draw_elevation_marker(
    draw: ImageDraw.ImageDraw,
    marker: ElevationMarkerLabel,
    plot_top: int,
    plot_bottom: int,
    *,
    scale: int,
) -> None:
    x = marker.spec.x
    _, _, _, label_bottom = marker.box
    draw.line((x, label_bottom, x, plot_bottom), fill=(255, 255, 255, 210), width=max(2, 2 * scale))
    label_left, label_top, _, _ = marker.box
    _draw_map_label_box(
        draw,
        label_left,
        label_top,
        marker.text,
        scale=scale,
        border_color=(148, 163, 184),
    )


def _elevation_profile_points(
    profile,
    *,
    distance_max: float,
    y_domain: tuple[float, float],
    plot_left: int,
    plot_right: int,
    plot_top: int,
    plot_bottom: int,
) -> list[tuple[float, float]]:
    return [
        (
            _scale_float(sample.distance_km, (0.0, distance_max), plot_left, plot_right),
            _scale_float(sample.elevation_m, y_domain, plot_bottom, plot_top),
        )
        for sample in profile.samples
    ]


def _elevation_marker_specs(
    profile,
    chart: RouteMap,
    points: list[tuple[float, float]],
) -> tuple[ElevationMarkerSpec, ...]:
    specs: list[ElevationMarkerSpec] = [
        ElevationMarkerSpec(
            label="Lähtö",
            elevation_m=profile.samples[0].elevation_m,
            x=points[0][0],
            priority=0,
            distance_km=profile.samples[0].distance_km,
            preferred_side="right",
        ),
        ElevationMarkerSpec(
            label="Maali",
            elevation_m=profile.samples[-1].elevation_m,
            x=points[-1][0],
            priority=1,
            distance_km=profile.samples[-1].distance_km,
            preferred_side="left",
        ),
    ]
    for waypoint in chart.waypoints[:10]:
        if waypoint.distance_km is None:
            continue
        waypoint_point = _elevation_point_at_distance(profile, waypoint.distance_km, points)
        if waypoint_point is None:
            continue
        x, _, elevation_m = waypoint_point
        specs.append(
            ElevationMarkerSpec(
                label=waypoint.label or "Reittimerkki",
                elevation_m=elevation_m,
                x=x,
                priority=2,
                distance_km=waypoint.distance_km,
                preferred_side="right",
            )
        )
    specs.append(
        ElevationMarkerSpec(
            label="Korkein kohta",
            elevation_m=profile.samples[profile.max_index].elevation_m,
            x=points[profile.max_index][0],
            priority=3,
            distance_km=profile.samples[profile.max_index].distance_km,
            preferred_side="right",
            required=False,
        )
    )
    if profile.min_index != profile.max_index:
        specs.append(
            ElevationMarkerSpec(
                label="Matalin kohta",
                elevation_m=profile.samples[profile.min_index].elevation_m,
                x=points[profile.min_index][0],
                priority=4,
                distance_km=profile.samples[profile.min_index].distance_km,
                preferred_side="right",
                required=False,
            )
        )
    return tuple(sorted(specs, key=lambda marker: (marker.priority, marker.distance_km)))


def _layout_elevation_marker_labels(
    draw: ImageDraw.ImageDraw,
    specs: tuple[ElevationMarkerSpec, ...],
    *,
    label_bounds: tuple[float, float, float, float],
    scale: int,
) -> tuple[ElevationMarkerLabel, ...]:
    placed: list[ElevationMarkerLabel] = []
    occupied_boxes: list[tuple[float, float, float, float]] = []
    for spec in specs:
        text = f"{spec.label} {round(spec.elevation_m)} m"
        for side, row in _elevation_label_candidate_order(spec.preferred_side):
            box = _elevation_marker_label_box(draw, spec, text, side, row, label_bounds=label_bounds, scale=scale)
            if box is None:
                continue
            if any(_boxes_overlap(box, existing, padding=3 * scale) for existing in occupied_boxes):
                continue
            placed_marker = ElevationMarkerLabel(spec=spec, text=text, box=box)
            placed.append(placed_marker)
            occupied_boxes.append(box)
            break
        else:
            if spec.required:
                box = _elevation_marker_label_box(draw, spec, text, spec.preferred_side, 0, label_bounds=label_bounds, scale=scale, clamp=True)
                if box is not None:
                    placed_marker = ElevationMarkerLabel(spec=spec, text=text, box=box)
                    placed.append(placed_marker)
                    occupied_boxes.append(box)
    return tuple(placed)


def _elevation_label_candidate_order(preferred_side: str) -> tuple[tuple[str, int], ...]:
    opposite = "left" if preferred_side == "right" else "right"
    return (
        (preferred_side, 0),
        (opposite, 0),
        (preferred_side, 1),
        (opposite, 1),
    )


def _elevation_marker_label_box(
    draw: ImageDraw.ImageDraw,
    spec: ElevationMarkerSpec,
    text: str,
    side: str,
    row: int,
    *,
    label_bounds: tuple[float, float, float, float],
    scale: int,
    clamp: bool = False,
) -> tuple[float, float, float, float] | None:
    min_x, min_y, max_x, max_y = label_bounds
    font = _font(10 * scale, bold=True)
    box_width, box_height = _map_label_size(draw, text, font=font, scale=scale)
    row_height = _elevation_label_row_height(draw, scale=scale)
    if row >= ELEVATION_LABEL_ROWS:
        return None
    y = min_y + row * row_height
    if y + box_height > max_y:
        return None
    if side == "left":
        x = spec.x - box_width
    else:
        x = spec.x
    if clamp:
        x = min(max(x, min_x), max_x - box_width)
    elif x < min_x or x + box_width > max_x:
        return None
    return (x, y, x + box_width, y + box_height)


def _elevation_label_row_height(draw: ImageDraw.ImageDraw, *, scale: int) -> int:
    _, box_height = _map_label_size(draw, "Korkein kohta 999 m", font=_font(10 * scale, bold=True), scale=scale)
    return box_height + 8 * scale


def _used_elevation_label_rows(
    labels: tuple[ElevationMarkerLabel, ...],
    top: int,
    draw: ImageDraw.ImageDraw,
    *,
    scale: int,
) -> int:
    if not labels:
        return 0
    row_height = _elevation_label_row_height(draw, scale=scale)
    return min(ELEVATION_LABEL_ROWS, max(1, max(math.floor((label.box[1] - top) / row_height) + 1 for label in labels)))


def _boxes_overlap(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
    *,
    padding: float = 0.0,
) -> bool:
    return not (
        first[2] + padding <= second[0]
        or second[2] + padding <= first[0]
        or first[3] + padding <= second[1]
        or second[3] + padding <= first[1]
    )


def _elevation_point_at_distance(
    profile,
    distance_km: float,
    points: list[tuple[float, float]],
) -> tuple[float, float, float] | None:
    samples = profile.samples
    if not samples:
        return None
    if distance_km <= samples[0].distance_km:
        return points[0][0], points[0][1], samples[0].elevation_m
    if distance_km >= samples[-1].distance_km:
        return points[-1][0], points[-1][1], samples[-1].elevation_m
    for index, (left_sample, right_sample) in enumerate(zip(samples, samples[1:], strict=False)):
        if left_sample.distance_km <= distance_km <= right_sample.distance_km:
            span = max(right_sample.distance_km - left_sample.distance_km, 0.000001)
            ratio = (distance_km - left_sample.distance_km) / span
            left_point = points[index]
            right_point = points[index + 1]
            x = left_point[0] + (right_point[0] - left_point[0]) * ratio
            y = left_point[1] + (right_point[1] - left_point[1]) * ratio
            elevation_m = left_sample.elevation_m + (right_sample.elevation_m - left_sample.elevation_m) * ratio
            return x, y, elevation_m
    return None


def _padded_elevation_domain(min_value: float, max_value: float) -> tuple[float, float]:
    span = max(max_value - min_value, 1.0)
    padding = max(3.0, span * 0.12)
    return min_value - padding, max_value + padding


def _draw_grade_scale(draw: ImageDraw.ImageDraw, profile, left: int, top: int, *, scale: int) -> None:
    font = _font(12 * scale)
    left, top, right, _ = _grade_scale_box(left, top, scale=scale)
    width = right - left
    height = 12 * scale
    for offset in range(width):
        ratio = offset / max(width - 1, 1)
        grade = -0.15 + ratio * 0.30
        draw.line((left + offset, top, left + offset, top + height), fill=_grade_color(grade) + (255,), width=1)
    draw.rectangle((left, top, left + width, top + height), outline=(255, 255, 255, 90), width=max(1, scale))
    label_y = top + height + 4 * scale
    _draw_text(draw, left, label_y, _format_grade(profile.min_grade), (226, 232, 240), font)
    _draw_text_center(draw, left + width // 2, label_y, "0%", (226, 232, 240), font)
    _draw_text_right(draw, left + width, label_y, _format_grade(profile.max_grade), (226, 232, 240), font)


def _grade_scale_box(left: int, top: int, *, scale: int) -> tuple[int, int, int, int]:
    return (left, top, left + 285 * scale, top + 34 * scale)


def _draw_elevation_distance_axis(
    draw: ImageDraw.ImageDraw,
    distance_max: float,
    left: int,
    right: int,
    y: int,
    *,
    scale: int,
) -> None:
    if distance_max <= 0:
        return
    tick_step = _distance_tick_step(distance_max)
    ticks: list[float] = [0.0]
    value = tick_step
    while value < distance_max - 0.001:
        ticks.append(value)
        value += tick_step
    if not math.isclose(ticks[-1], distance_max):
        ticks.append(distance_max)
    axis_color = (226, 232, 240)
    muted = (203, 213, 225)
    font = _font(10 * scale)
    draw.line((left, y, right, y), fill=axis_color + (150,), width=max(1, scale))
    for tick in ticks:
        x = _scale_float(tick, (0.0, distance_max), left, right)
        draw.line((x, y, x, y + 5 * scale), fill=axis_color + (170,), width=max(1, scale))
        label = f"{tick:.0f} km" if math.isclose(tick, distance_max) else f"{tick:.0f}"
        if math.isclose(tick, 0.0):
            _draw_text(draw, round(x), y + 7 * scale, label, muted, font)
        elif math.isclose(tick, distance_max):
            _draw_text_right(draw, round(x), y + 7 * scale, label, muted, font)
        else:
            _draw_text_center(draw, round(x), y + 7 * scale, label, muted, font)


def _distance_tick_step(distance_km: float) -> float:
    if distance_km <= 5:
        return 1.0
    if distance_km <= 15:
        return 2.0
    if distance_km <= 40:
        return 5.0
    if distance_km <= 100:
        return 10.0
    return 20.0


def _format_grade(grade: float) -> str:
    value = round(grade * 100)
    return f"{value:+d}%"


def _grade_color(grade: float) -> tuple[int, int, int]:
    percent = grade * 100
    stops = (
        (-15.0, (126, 34, 206)),
        (-12.0, (126, 34, 206)),
        (-6.0, (37, 99, 235)),
        (-1.0, (22, 163, 74)),
        (2.0, (203, 213, 225)),
        (6.0, (250, 204, 21)),
        (10.0, (249, 115, 22)),
        (15.0, (220, 38, 38)),
    )
    if percent <= stops[0][0]:
        return stops[0][1]
    for (left_value, left_color), (right_value, right_color) in zip(stops, stops[1:], strict=False):
        if percent <= right_value:
            ratio = (percent - left_value) / max(right_value - left_value, 0.000001)
            return _lerp_color(left_color, right_color, max(0.0, min(1.0, ratio)))
    return stops[-1][1]


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
    radius = ROUTE_MARKER_RADIUS * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 230), outline=color + (255,), width=2 * scale)
    inner = 3 * scale
    draw.ellipse((x - inner, y - inner, x + inner, y + inner), fill=color + (255,))


def _draw_waypoint_marker(
    draw: ImageDraw.ImageDraw,
    point: tuple[float, float],
    waypoint_type: str,
    color: tuple[int, int, int],
    *,
    scale: int,
) -> None:
    x, y = point
    icon_color = _waypoint_color(waypoint_type) or color
    radius = ROUTE_MARKER_RADIUS * scale
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(255, 255, 255, 242), outline=icon_color + (255,), width=2 * scale)
    icon_font = _waypoint_icon_font(8 * scale)
    icon = _waypoint_icon_text(waypoint_type)
    if icon_font is not None:
        text_width, text_height = _text_size(draw, icon, icon_font)
        _draw_text(draw, round(x - text_width / 2), round(y - text_height / 2), icon, icon_color, icon_font)
        return
    fallback = _waypoint_fallback_icon(waypoint_type)
    font = _font(8 * scale, bold=True)
    text_width, text_height = _text_size(draw, fallback, font)
    _draw_text(draw, round(x - text_width / 2), round(y - text_height / 2), fallback, icon_color, font)


def _waypoint_icon_text(waypoint_type: str) -> str:
    normalized = _waypoint_type_key(waypoint_type)
    return {
        "info": "\uf129",
        "checkpoint": "\uf11e",
        "summit": "\uf6fc",
        "water": "\uf773",
        "food": "\uf2e7",
    }.get(normalized, "\uf3c5")


def _waypoint_fallback_icon(waypoint_type: str) -> str:
    normalized = _waypoint_type_key(waypoint_type)
    return {
        "info": "i",
        "checkpoint": "C",
        "summit": "^",
        "water": "W",
        "food": "F",
    }.get(normalized, "*")


def _waypoint_color(waypoint_type: str) -> tuple[int, int, int]:
    normalized = _waypoint_type_key(waypoint_type)
    return {
        "info": (37, 99, 235),
        "checkpoint": (22, 163, 74),
        "summit": (124, 58, 237),
        "water": (8, 145, 178),
        "food": (249, 115, 22),
    }.get(normalized, (124, 58, 237))


def _waypoint_type_key(waypoint_type: str) -> str:
    text = waypoint_type.strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"information", "info_point"}:
        return "info"
    if text in {"check_point", "control", "control_point"}:
        return "checkpoint"
    return text


@lru_cache(maxsize=16)
def _waypoint_icon_font(size: int) -> ImageFont.FreeTypeFont | None:
    path = _fontawesome_solid_path()
    if path is None:
        return None
    try:
        return ImageFont.truetype(path, size=max(8, size))
    except OSError:
        return None


@lru_cache(maxsize=1)
def _fontawesome_solid_path() -> str | None:
    try:
        root = resources.files("fontawesomefree")
    except ModuleNotFoundError:
        return None
    candidates = (
        root / "static" / "fontawesomefree" / "webfonts" / "fa-solid-900.ttf",
        root / "webfonts" / "fa-solid-900.ttf",
        root / "fa-solid-900.ttf",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _scale_float(value: float, domain: tuple[float, float], low_px: int, high_px: int) -> float:
    low, high = domain
    if math.isclose(high, low):
        return (low_px + high_px) / 2.0
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


def _draw_map_label(
    draw: ImageDraw.ImageDraw,
    anchor_x: float,
    anchor_y: float,
    text: str,
    *,
    side: str,
    bounds: tuple[float, float, float, float],
    scale: int,
    border_color: tuple[int, int, int] = (148, 163, 184),
    gap: int | None = None,
    font: ImageFont.ImageFont | None = None,
) -> tuple[float, float, float, float]:
    label_font = font or _font(10 * scale, bold=True)
    gap = 7 * scale if gap is None else gap
    box_width, box_height = _map_label_size(draw, text, font=label_font, scale=scale)
    min_x, min_y, max_x, max_y = bounds
    if side == "left":
        label_x = anchor_x - gap - box_width
    elif side == "center":
        label_x = anchor_x - box_width / 2
    else:
        label_x = anchor_x + gap
    label_y = anchor_y - gap - box_height
    label_x = min(max(label_x, min_x), max_x - box_width)
    label_y = min(max(label_y, min_y), max_y - box_height)
    return _draw_map_label_box(draw, label_x, label_y, text, scale=scale, border_color=border_color, font=label_font)


def _draw_map_label_box(
    draw: ImageDraw.ImageDraw,
    label_x: float,
    label_y: float,
    text: str,
    *,
    scale: int,
    border_color: tuple[int, int, int] = (148, 163, 184),
    fill_color: tuple[int, int, int, int] = (255, 255, 255, 232),
    text_color: tuple[int, int, int] = TEXT,
    font: ImageFont.ImageFont | None = None,
) -> tuple[float, float, float, float]:
    label_font = font or _font(10 * scale, bold=True)
    box_width, box_height = _map_label_size(draw, text, font=label_font, scale=scale)
    bbox = (label_x, label_y, label_x + box_width, label_y + box_height)
    draw.rounded_rectangle(bbox, radius=4 * scale, fill=fill_color, outline=border_color + (230,), width=max(1, scale))
    padding_x, padding_y = _map_label_padding(scale)
    _draw_text(draw, int(label_x + padding_x), int(label_y + padding_y), text, text_color, label_font)
    return bbox


def _map_label_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    scale: int,
) -> tuple[int, int]:
    padding_x, padding_y = _map_label_padding(scale)
    text_width, text_height = _text_size(draw, text, font)
    return text_width + 2 * padding_x, text_height + 2 * padding_y


def _map_label_padding(scale: int) -> tuple[int, int]:
    return 7 * scale, 4 * scale


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


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    font: ImageFont.ImageFont,
    *,
    max_lines: int,
) -> tuple[str, ...]:
    words = [word for word in text.split() if word]
    if not words:
        return ("",)
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and _text_size(draw, candidate, font)[0] > max_width:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
        else:
            current = candidate
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if lines:
        lines[-1] = _ellipsize_to_width(draw, lines[-1], max_width, font)
    return tuple(lines)


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
