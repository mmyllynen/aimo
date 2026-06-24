from __future__ import annotations

import shutil
import subprocess
import math
import tempfile
import os
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from core.config import MapsConfig
from storage.repositories import WorkoutPointRecord, WorkoutRecord
from visualization.render import _mercator_xy
from visualization.tiles import TileCoord, TileFetchConfig, TileFetchError, TileImage, fetch_tiles


EARTH_CIRCUMFERENCE_M = 40075016.686
DEFAULT_OSM_ATTRIBUTION = "© OpenStreetMap contributors"


@dataclass(frozen=True)
class OverlayAnimationRequest:
    start_km: float = 0.0
    window_km: float = 0.5
    length_s: float = 5.0
    fps: int = 10
    width: int = 1280
    height: int = 720
    overlay_types: tuple[str, ...] = ("map",)
    show_map: bool = True
    show_speed: bool = True
    show_hr: bool = True
    sync: str = "fit"
    view: str = "segment"
    radius_km: float = 0.3
    tail_km: float = 0.2
    tail_mode: str = "time"
    tail_time_s: float = 30.0
    tail_max_km: float = 0.25
    lookahead_km: float = 0.1
    auto_zoom: bool = True
    radius_min_km: float = 0.1
    tail_min_km: float = 0.06
    auto_zoom_fast_pace_s_per_km: float = 240.0
    auto_zoom_slow_pace_s_per_km: float = 540.0
    auto_zoom_sample_s: float = 20.0
    output_format: str = "mov"
    transparent: bool = True
    map_layout: str = "circle"
    hr_layout: str = "line"
    map_mode: str = "tiles"
    compass: bool = True
    map_style: str = "streets-v2-dark"
    tile_alpha: float = 0.9
    route_position: str = "right"
    route_size: int = 360
    route_background: str = "dim"
    route_tail: bool = True


@dataclass(frozen=True)
class OverlayAnimationArtifact:
    filename: str
    content_type: str
    content: bytes
    metadata: dict[str, object]


class OverlayAnimationEncodingError(RuntimeError):
    pass


class OverlayAnimationEncoderUnavailableError(OverlayAnimationEncodingError):
    pass


@dataclass(frozen=True)
class TileProvider:
    name: str
    background: str
    attribution: str
    tile_size: int
    config: TileFetchConfig


@dataclass(frozen=True)
class OverlayCamera:
    center: WorkoutPointRecord
    zoom: int
    tile_size: int
    diameter: int
    world_left: float
    world_top: float
    render_world_left: int
    render_world_top: int


@dataclass(frozen=True)
class OverviewProjection:
    origin_x: float
    origin_y: float
    x_low: float
    y_low: float
    scale: float


def render_workout_overlay_animation(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    request: OverlayAnimationRequest,
    *,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
) -> OverlayAnimationArtifact:
    return _render_map_overlay_animation(
        workout,
        points,
        request,
        tile_cache_root=tile_cache_root,
        maps_config=maps_config,
    )


def render_workout_overlay_bundle(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    request: OverlayAnimationRequest,
    *,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
) -> tuple[OverlayAnimationArtifact, ...]:
    artifacts: list[OverlayAnimationArtifact] = []
    for overlay_type in request.overlay_types:
        if overlay_type == "map":
            artifacts.append(
                _render_map_overlay_animation(
                    workout,
                    points,
                    replace(
                        request,
                        show_map=True,
                        show_speed=False,
                        show_hr=False,
                    ),
                    tile_cache_root=tile_cache_root,
                    maps_config=maps_config,
                )
            )
        elif overlay_type == "route":
            artifacts.append(_render_route_overview_animation(workout, points, request))
        elif overlay_type == "hr":
            artifacts.append(_render_hr_overlay_animation(workout, points, request))
    if not artifacts:
        raise ValueError("overlay animation requires at least one overlay type")
    return tuple(artifacts)


def _render_map_overlay_animation(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    request: OverlayAnimationRequest,
    *,
    tile_cache_root: Path | None = None,
    maps_config: MapsConfig | None = None,
) -> OverlayAnimationArtifact:
    route_points = tuple(point for point in points if point.latitude is not None and point.longitude is not None)
    if len(route_points) < 2:
        raise ValueError("overlay animation requires route points")
    distance_points = tuple(point for point in route_points if point.distance_km is not None)
    if len(distance_points) < 2:
        raise ValueError("overlay animation requires distance samples")

    start_km = max(0.0, request.start_km)
    total_km = max(float(point.distance_km or 0.0) for point in distance_points)
    if start_km >= total_km:
        start_km = max(0.0, total_km - request.window_km)
    end_km = min(total_km, start_km + max(0.05, request.window_km))
    segment = _segment_points(route_points, start_km, end_km)
    if len(segment) < 2:
        segment = distance_points[:2]

    frame_count = max(2, min(2400, int(round(request.length_s * request.fps))))
    duration_ms = max(20, int(round(1000 / max(1, request.fps))))
    timeline_points = tuple(point for point in distance_points if point.elapsed_s is not None)
    if request.sync == "real":
        if len(timeline_points) < 2:
            raise ValueError("real-time overlay animation requires elapsed time samples")
        start_elapsed_s = _elapsed_at_distance(timeline_points, start_km)
        end_elapsed_s = min(float(timeline_points[-1].elapsed_s or 0.0), start_elapsed_s + request.length_s)
        if end_elapsed_s <= start_elapsed_s:
            raise ValueError("real-time overlay animation has no remaining timed route")
        frame_count = max(2, min(frame_count, int(round((end_elapsed_s - start_elapsed_s) * request.fps)) + 1))
    else:
        start_elapsed_s = None
        end_elapsed_s = None
    tile_context = _tile_context(tile_cache_root, maps_config, map_style=request.map_style) if request.map_mode == "tiles" else None
    frames = [
        _render_frame(
            workout,
            segment,
            route_points=route_points,
            timeline_points=timeline_points,
            tile_context=tile_context,
            frame_index=index,
            frame_count=frame_count,
            request=request,
            start_km=start_km,
            end_km=end_km,
            start_elapsed_s=start_elapsed_s,
            end_elapsed_s=end_elapsed_s,
        )
        for index in range(frame_count)
    ]
    output_format = request.output_format if request.output_format in {"gif", "webm", "mov", "mp4"} else ("mov" if request.transparent else "mp4")
    content, extension, content_type = _encoded_frames(frames, output_format=output_format, fps=request.fps, duration_ms=duration_ms)
    filename = _overlay_filename(workout, start_km, end_km, "map", extension)
    return OverlayAnimationArtifact(
        filename=filename,
        content_type=content_type,
        content=content,
        metadata={
            "chart_type": "animation_overlay",
            "overlay_type": "map",
            "format": output_format,
            "workout_id": workout.workout_id,
            "start_km": round(start_km, 3),
            "end_km": round(end_km, 3),
            "window_km": round(end_km - start_km, 3),
            "length_s": request.length_s,
            "fps": request.fps,
            "frame_count": frame_count,
            "render_width": request.width,
            "render_height": request.height,
            "show_map": request.show_map,
            "show_speed": request.show_speed,
            "show_hr": request.show_hr,
            "sync": request.sync,
            "view": request.view,
            "radius_km": request.radius_km,
            "tail_km": request.tail_km,
            "tail_mode": request.tail_mode,
            "tail_time_s": request.tail_time_s,
            "tail_max_km": request.tail_max_km,
            "lookahead_km": request.lookahead_km,
            "auto_zoom": request.auto_zoom,
            "radius_min_km": request.radius_min_km,
            "tail_min_km": request.tail_min_km,
            "auto_zoom_fast_pace_s_per_km": request.auto_zoom_fast_pace_s_per_km,
            "auto_zoom_slow_pace_s_per_km": request.auto_zoom_slow_pace_s_per_km,
            "auto_zoom_sample_s": request.auto_zoom_sample_s,
            "transparent": request.transparent,
            "map_layout": request.map_layout,
            "map_mode": request.map_mode,
            "compass": request.compass,
            "map_style": request.map_style,
            "tile_alpha": request.tile_alpha,
            "start_elapsed_s": round(start_elapsed_s, 1) if start_elapsed_s is not None else None,
            "end_elapsed_s": round(end_elapsed_s, 1) if end_elapsed_s is not None else None,
            **_tile_metadata(tile_context),
        },
    )


def _render_route_overview_animation(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    request: OverlayAnimationRequest,
) -> OverlayAnimationArtifact:
    route_points = tuple(point for point in points if point.latitude is not None and point.longitude is not None)
    if len(route_points) < 2:
        raise ValueError("overlay animation requires route points")
    distance_points = tuple(point for point in route_points if point.distance_km is not None)
    if len(distance_points) < 2:
        raise ValueError("overlay animation requires distance samples")

    start_km = max(0.0, request.start_km)
    total_km = max(float(point.distance_km or 0.0) for point in distance_points)
    if start_km >= total_km:
        start_km = max(0.0, total_km - request.window_km)
    end_km = min(total_km, start_km + max(0.05, request.window_km))
    segment = _segment_points(route_points, start_km, end_km)
    if len(segment) < 2:
        segment = distance_points[:2]

    frame_count = max(2, min(2400, int(round(request.length_s * request.fps))))
    duration_ms = max(20, int(round(1000 / max(1, request.fps))))
    timeline_points = tuple(point for point in distance_points if point.elapsed_s is not None)
    if request.sync == "real":
        if len(timeline_points) < 2:
            raise ValueError("real-time overlay animation requires elapsed time samples")
        start_elapsed_s = _elapsed_at_distance(timeline_points, start_km)
        end_elapsed_s = min(float(timeline_points[-1].elapsed_s or 0.0), start_elapsed_s + request.length_s)
        if end_elapsed_s <= start_elapsed_s:
            raise ValueError("real-time overlay animation has no remaining timed route")
        frame_count = max(2, min(frame_count, int(round((end_elapsed_s - start_elapsed_s) * request.fps)) + 1))
    else:
        start_elapsed_s = None
        end_elapsed_s = None

    frames = [
        _render_route_overview_frame(
            route_points,
            segment=segment,
            frame_index=index,
            frame_count=frame_count,
            request=request,
            start_km=start_km,
            end_km=end_km,
            start_elapsed_s=start_elapsed_s,
            end_elapsed_s=end_elapsed_s,
        )
        for index in range(frame_count)
    ]
    output_format = request.output_format if request.output_format in {"gif", "webm", "mov", "mp4"} else ("mov" if request.transparent else "mp4")
    content, extension, content_type = _encoded_frames(frames, output_format=output_format, fps=request.fps, duration_ms=duration_ms)
    filename = _overlay_filename(workout, start_km, end_km, "route", extension)
    return OverlayAnimationArtifact(
        filename=filename,
        content_type=content_type,
        content=content,
        metadata={
            "chart_type": "animation_overlay",
            "overlay_type": "route",
            "format": output_format,
            "workout_id": workout.workout_id,
            "start_km": round(start_km, 3),
            "end_km": round(end_km, 3),
            "window_km": round(end_km - start_km, 3),
            "length_s": request.length_s,
            "fps": request.fps,
            "frame_count": frame_count,
            "render_width": request.width,
            "render_height": request.height,
            "sync": request.sync,
            "view": request.view,
            "tail_km": request.tail_km,
            "tail_mode": request.tail_mode,
            "tail_time_s": request.tail_time_s,
            "tail_max_km": request.tail_max_km,
            "tail_min_km": request.tail_min_km,
            "transparent": request.transparent,
            "route_position": request.route_position,
            "route_size": request.route_size,
            "route_background": request.route_background,
            "route_tail": request.route_tail,
            "start_elapsed_s": round(start_elapsed_s, 1) if start_elapsed_s is not None else None,
            "end_elapsed_s": round(end_elapsed_s, 1) if end_elapsed_s is not None else None,
        },
    )


def _render_hr_overlay_animation(
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    request: OverlayAnimationRequest,
) -> OverlayAnimationArtifact:
    distance_points = tuple(point for point in points if point.distance_km is not None)
    if len(distance_points) < 2:
        raise ValueError("overlay animation requires distance samples")
    hr_points = tuple(point for point in distance_points if point.heart_rate_bpm is not None)
    if len(hr_points) < 2:
        raise ValueError("overlay animation requires heart rate samples")

    start_km = max(0.0, request.start_km)
    total_km = max(float(point.distance_km or 0.0) for point in distance_points)
    if start_km >= total_km:
        start_km = max(0.0, total_km - request.window_km)
    end_km = min(total_km, start_km + max(0.05, request.window_km))
    segment = _segment_points(distance_points, start_km, end_km)
    if len(segment) < 2:
        segment = distance_points[:2]

    frame_count = max(2, min(2400, int(round(request.length_s * request.fps))))
    duration_ms = max(20, int(round(1000 / max(1, request.fps))))
    timeline_points = tuple(point for point in distance_points if point.elapsed_s is not None)
    if request.sync == "real":
        if len(timeline_points) < 2:
            raise ValueError("real-time overlay animation requires elapsed time samples")
        start_elapsed_s = _elapsed_at_distance(timeline_points, start_km)
        end_elapsed_s = min(float(timeline_points[-1].elapsed_s or 0.0), start_elapsed_s + request.length_s)
        if end_elapsed_s <= start_elapsed_s:
            raise ValueError("real-time overlay animation has no remaining timed route")
        frame_count = max(2, min(frame_count, int(round((end_elapsed_s - start_elapsed_s) * request.fps)) + 1))
    else:
        start_elapsed_s = None
        end_elapsed_s = None

    frames = [
        _render_hr_frame(
            workout,
            distance_points,
            segment=segment,
            frame_index=index,
            frame_count=frame_count,
            request=request,
            start_km=start_km,
            end_km=end_km,
            start_elapsed_s=start_elapsed_s,
            end_elapsed_s=end_elapsed_s,
        )
        for index in range(frame_count)
    ]
    output_format = request.output_format if request.output_format in {"gif", "webm", "mov", "mp4"} else ("mov" if request.transparent else "mp4")
    content, extension, content_type = _encoded_frames(frames, output_format=output_format, fps=request.fps, duration_ms=duration_ms)
    filename = _overlay_filename(workout, start_km, end_km, "hr", extension)
    return OverlayAnimationArtifact(
        filename=filename,
        content_type=content_type,
        content=content,
        metadata={
            "chart_type": "animation_overlay",
            "overlay_type": "hr",
            "format": output_format,
            "workout_id": workout.workout_id,
            "start_km": round(start_km, 3),
            "end_km": round(end_km, 3),
            "window_km": round(end_km - start_km, 3),
            "length_s": request.length_s,
            "fps": request.fps,
            "frame_count": frame_count,
            "render_width": request.width,
            "render_height": request.height,
            "sync": request.sync,
            "view": request.view,
            "tail_km": request.tail_km,
            "tail_mode": request.tail_mode,
            "tail_time_s": request.tail_time_s,
            "tail_max_km": request.tail_max_km,
            "auto_zoom": request.auto_zoom,
            "tail_min_km": request.tail_min_km,
            "auto_zoom_fast_pace_s_per_km": request.auto_zoom_fast_pace_s_per_km,
            "auto_zoom_slow_pace_s_per_km": request.auto_zoom_slow_pace_s_per_km,
            "auto_zoom_sample_s": request.auto_zoom_sample_s,
            "transparent": request.transparent,
            "hr_layout": request.hr_layout,
            "start_elapsed_s": round(start_elapsed_s, 1) if start_elapsed_s is not None else None,
            "end_elapsed_s": round(end_elapsed_s, 1) if end_elapsed_s is not None else None,
        },
    )


def _segment_points(
    points: tuple[WorkoutPointRecord, ...],
    start_km: float,
    end_km: float,
) -> tuple[WorkoutPointRecord, ...]:
    selected = tuple(
        point
        for point in points
        if point.distance_km is not None and start_km <= float(point.distance_km) <= end_km
    )
    if len(selected) >= 2:
        return selected
    before = tuple(point for point in points if point.distance_km is not None and float(point.distance_km) < start_km)
    after = tuple(point for point in points if point.distance_km is not None and float(point.distance_km) > end_km)
    expanded = before[-1:] + selected + after[:1]
    return expanded if len(expanded) >= 2 else selected


def _distance_segment_points(
    points: tuple[WorkoutPointRecord, ...],
    start_km: float,
    end_km: float,
) -> tuple[WorkoutPointRecord, ...]:
    distance_points = tuple(point for point in points if point.distance_km is not None)
    if len(distance_points) < 2:
        return distance_points
    start_km = max(float(distance_points[0].distance_km or 0.0), start_km)
    end_km = min(float(distance_points[-1].distance_km or 0.0), end_km)
    if end_km < start_km:
        start_km, end_km = end_km, start_km
    selected = tuple(
        point
        for point in distance_points
        if start_km < float(point.distance_km or 0.0) < end_km
    )
    start = _point_at_distance(distance_points, start_km)
    end = _point_at_distance(distance_points, end_km)
    if math.isclose(start_km, end_km, abs_tol=0.000001):
        return (end,)
    return (start, *selected, end)


def _tail_start_km(
    points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    request: OverlayAnimationRequest,
    *,
    fallback_start_km: float = 0.0,
) -> float:
    current_km = float(current.distance_km or fallback_start_km)
    if request.tail_mode == "time" and current.elapsed_s is not None:
        timeline = tuple(point for point in points if point.elapsed_s is not None and point.distance_km is not None)
        if len(timeline) >= 2:
            current_elapsed = float(current.elapsed_s)
            first_elapsed = float(timeline[0].elapsed_s or 0.0)
            start_elapsed = max(first_elapsed, current_elapsed - max(1.0, request.tail_time_s))
            start = _point_at_elapsed(timeline, start_elapsed)
            if start.distance_km is not None:
                raw_tail_km = max(0.0, current_km - float(start.distance_km))
                min_tail_km = min(request.tail_max_km, max(0.0, request.tail_min_km))
                bounded_tail_km = _clamp(raw_tail_km, min_tail_km, max(min_tail_km, request.tail_max_km))
                return max(fallback_start_km, current_km - bounded_tail_km)
    return max(fallback_start_km, current_km - max(0.0, request.tail_km))


def _render_frame(
    workout: WorkoutRecord,
    segment: tuple[WorkoutPointRecord, ...],
    *,
    route_points: tuple[WorkoutPointRecord, ...],
    timeline_points: tuple[WorkoutPointRecord, ...],
    tile_context: dict[str, Any] | None,
    frame_index: int,
    frame_count: int,
    request: OverlayAnimationRequest,
    start_km: float,
    end_km: float,
    start_elapsed_s: float | None,
    end_elapsed_s: float | None,
) -> Image.Image:
    image = Image.new("RGBA", (request.width, request.height), (0, 0, 0, 0) if request.transparent else (12, 17, 24, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    progress = frame_index / max(1, frame_count - 1)
    current = (
        _point_at_elapsed(timeline_points, start_elapsed_s + progress * max(0.0, (end_elapsed_s or start_elapsed_s or 0.0) - (start_elapsed_s or 0.0)))
        if request.sync == "real" and start_elapsed_s is not None and end_elapsed_s is not None
        else _point_at_progress(segment, progress)
    )
    if not request.transparent:
        _draw_background(draw, request.width, request.height)
    if request.show_map:
        frame_request = _auto_zoom_request(route_points, current, request)
        if request.map_layout == "circle":
            _draw_circle_route_map(image, route_points, current, frame_request, tile_context)
        elif request.view == "local":
            _draw_local_route_map(draw, route_points, current, request.width, request.height, frame_request)
        else:
            _draw_route_map(draw, segment, current, request.width, request.height)
    if not (request.transparent and request.show_map and not request.show_speed and not request.show_hr):
        _draw_title(draw, workout, start_km, end_km)
    if request.show_speed:
        _draw_speed_gauge(draw, current, segment, request.width, request.height)
    if request.show_hr:
        _draw_hr_gauge(draw, current, request.width, request.height)
    return image


def _render_hr_frame(
    workout: WorkoutRecord,
    distance_points: tuple[WorkoutPointRecord, ...],
    *,
    segment: tuple[WorkoutPointRecord, ...],
    frame_index: int,
    frame_count: int,
    request: OverlayAnimationRequest,
    start_km: float,
    end_km: float,
    start_elapsed_s: float | None,
    end_elapsed_s: float | None,
) -> Image.Image:
    image = Image.new("RGBA", (request.width, request.height), (0, 0, 0, 0) if request.transparent else (12, 17, 24, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    progress = frame_index / max(1, frame_count - 1)
    timeline_points = tuple(point for point in distance_points if point.elapsed_s is not None)
    current = (
        _point_at_elapsed(timeline_points, start_elapsed_s + progress * max(0.0, (end_elapsed_s or start_elapsed_s or 0.0) - (start_elapsed_s or 0.0)))
        if request.sync == "real" and start_elapsed_s is not None and end_elapsed_s is not None and len(timeline_points) >= 2
        else _point_at_progress(segment, progress)
    )
    if not request.transparent:
        _draw_background(draw, request.width, request.height)
    _draw_hr_curve_overlay(draw, workout, distance_points, current, _auto_zoom_request(distance_points, current, request), start_km, end_km)
    return image


def _render_route_overview_frame(
    route_points: tuple[WorkoutPointRecord, ...],
    *,
    segment: tuple[WorkoutPointRecord, ...],
    frame_index: int,
    frame_count: int,
    request: OverlayAnimationRequest,
    start_km: float,
    end_km: float,
    start_elapsed_s: float | None,
    end_elapsed_s: float | None,
) -> Image.Image:
    image = Image.new("RGBA", (request.width, request.height), (0, 0, 0, 0) if request.transparent else (12, 17, 24, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    progress = frame_index / max(1, frame_count - 1)
    timeline_points = tuple(point for point in route_points if point.elapsed_s is not None and point.distance_km is not None)
    current = (
        _point_at_elapsed(timeline_points, start_elapsed_s + progress * max(0.0, (end_elapsed_s or start_elapsed_s or 0.0) - (start_elapsed_s or 0.0)))
        if request.sync == "real" and start_elapsed_s is not None and end_elapsed_s is not None and len(timeline_points) >= 2
        else _point_at_progress(segment, progress)
    )
    if not request.transparent:
        _draw_background(draw, request.width, request.height)
    _draw_route_overview_overlay(draw, route_points, current, request)
    return image


def _draw_hr_curve_overlay(
    draw: ImageDraw.ImageDraw,
    workout: WorkoutRecord,
    points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    request: OverlayAnimationRequest,
    start_km: float,
    end_km: float,
) -> None:
    margin_x = max(24, int(request.width * 0.045))
    panel_height = max(128, min(int(request.height * 0.34), 240))
    panel_bottom = request.height - max(24, int(request.height * 0.055))
    panel = (margin_x, panel_bottom - panel_height, request.width - margin_x, panel_bottom)
    if panel[2] - panel[0] < 240 or panel[3] - panel[1] < 96:
        return

    fill_alpha = 178 if request.transparent else 225
    draw.rounded_rectangle(panel, radius=18, fill=(15, 23, 42, fill_alpha), outline=(248, 250, 252, 220), width=2)
    current_km = float(current.distance_km or start_km)
    tail_start = _tail_start_km(points, current, request, fallback_start_km=start_km)
    visible = tuple(
        point
        for point in points
        if point.distance_km is not None and point.heart_rate_bpm is not None and tail_start <= float(point.distance_km) <= current_km
    )
    if current.heart_rate_bpm is not None and (not visible or float(visible[-1].distance_km or 0.0) < current_km):
        visible = (*visible, current)
    if len(visible) < 2:
        visible = tuple(point for point in points if point.distance_km is not None and point.heart_rate_bpm is not None and start_km <= float(point.distance_km) <= end_km)
    if len(visible) < 2:
        return

    inner = (panel[0] + 28, panel[1] + 28, panel[2] - 118, panel[3] - 26)
    hr_values = tuple(float(point.heart_rate_bpm or 0.0) for point in visible if point.heart_rate_bpm is not None)
    low = max(40.0, min(hr_values) - 6.0)
    high = max(low + 10.0, max(hr_values) + 6.0)
    low_distance = min(float(point.distance_km or current_km) for point in visible)
    high_distance = max(current_km, max(float(point.distance_km or current_km) for point in visible))
    if high_distance <= low_distance:
        high_distance = low_distance + max(0.02, request.tail_km)

    grid_color = (148, 163, 184, 75)
    for index in range(1, 3):
        y = inner[1] + int((inner[3] - inner[1]) * index / 3)
        draw.line((inner[0], y, inner[2], y), fill=grid_color, width=1)

    def project(point: WorkoutPointRecord) -> tuple[int, int]:
        distance = float(point.distance_km or low_distance)
        hr = float(point.heart_rate_bpm or low)
        x = inner[0] + int((distance - low_distance) / max(0.000001, high_distance - low_distance) * (inner[2] - inner[0]))
        y = inner[3] - int((hr - low) / max(0.000001, high - low) * (inner[3] - inner[1]))
        return x, y

    projected = tuple(project(point) for point in visible)
    if len(projected) >= 2:
        for first, second in zip(projected, projected[1:]):
            draw.line((first, second), fill=(248, 113, 113, 245), width=5)
    current_xy = projected[-1]
    draw.ellipse((current_xy[0] - 7, current_xy[1] - 7, current_xy[0] + 7, current_xy[1] + 7), fill=(248, 250, 252, 255), outline=(185, 28, 28, 255), width=3)

    title_font = _font(15)
    value_font = _font(42)
    unit_font = _font(15)
    small_font = _font(12)
    hr_value = "--" if current.heart_rate_bpm is None else str(int(round(current.heart_rate_bpm)))
    draw.text((panel[0] + 28, panel[1] + 10), "HR", font=title_font, fill=(248, 250, 252, 230))
    draw.text((panel[2] - 96, panel[1] + 30), hr_value, font=value_font, fill=(248, 250, 252, 255))
    draw.text((panel[2] - 90, panel[1] + 78), "bpm", font=unit_font, fill=(203, 213, 225, 235))
    draw.text((panel[0] + 70, panel[1] + 12), _ellipsize(workout.title or workout.workout_id, 42), font=small_font, fill=(203, 213, 225, 210))


def _draw_route_overview_overlay(
    draw: ImageDraw.ImageDraw,
    route_points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    request: OverlayAnimationRequest,
) -> None:
    panel = _route_overview_panel(request)
    if panel[2] - panel[0] < 96 or panel[3] - panel[1] < 96:
        return
    if request.route_background == "dim":
        fill_alpha = 120 if request.transparent else 200
        draw.rounded_rectangle(panel, radius=18, fill=(15, 23, 42, fill_alpha), outline=(248, 250, 252, 170), width=2)

    route = tuple(point for point in route_points if point.latitude is not None and point.longitude is not None and point.distance_km is not None)
    if len(route) < 2:
        return
    projection = _overview_projection(route, panel)
    display_route = _thin_points(route, max_points=1600)
    current_km = float(current.distance_km or 0.0)
    completed = _thin_points(_distance_segment_points(route, 0.0, current_km), max_points=1600)
    tail_start = _tail_start_km(route, current, request)
    tail = _distance_segment_points(route, tail_start, current_km) if request.route_tail else ()

    _draw_overview_line(draw, display_route, projection, fill=(248, 250, 252, 135), width=4)
    _draw_overview_line(draw, completed, projection, fill=(96, 165, 250, 220), width=5)
    if tail:
        _draw_overview_line(draw, tail, projection, fill=(37, 99, 235, 255), width=7)

    marker = _project_overview(current, projection)
    draw.ellipse(
        (marker[0] - 9, marker[1] - 9, marker[0] + 9, marker[1] + 9),
        fill=(245, 158, 11, 255),
        outline=(255, 255, 255, 255),
        width=3,
    )


def _route_overview_panel(request: OverlayAnimationRequest) -> tuple[int, int, int, int]:
    size = max(120, min(request.route_size, request.width - 24, request.height - 24))
    margin = max(12, int(min(request.width, request.height) * 0.04))
    top = margin
    if request.route_position == "left":
        left = margin
    elif request.route_position == "center":
        left = (request.width - size) // 2
        top = (request.height - size) // 2
    else:
        left = request.width - margin - size
    return (left, top, left + size, top + size)


def _draw_overview_line(
    draw: ImageDraw.ImageDraw,
    points: tuple[WorkoutPointRecord, ...],
    projection: OverviewProjection,
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    route = tuple(_project_overview(point, projection) for point in points if point.latitude is not None and point.longitude is not None)
    if len(route) >= 2:
        for first, second in zip(route, route[1:]):
            draw.line((first, second), fill=fill, width=width)


def _overview_projection(
    route_points: tuple[WorkoutPointRecord, ...],
    panel: tuple[int, int, int, int],
) -> OverviewProjection:
    projected = tuple(_mercator_xy(float(item.latitude), float(item.longitude)) for item in route_points if item.latitude is not None and item.longitude is not None)
    x_values = tuple(item[0] for item in projected)
    y_values = tuple(item[1] for item in projected)
    x_low, x_high = _padded(min(x_values), max(x_values))
    y_low, y_high = _padded(min(y_values), max(y_values))
    left, top, right, bottom = panel
    inset = max(16, int((right - left) * 0.08))
    inner_width = max(1, right - left - inset * 2)
    inner_height = max(1, bottom - top - inset * 2)
    scale = min(inner_width / max(0.000001, x_high - x_low), inner_height / max(0.000001, y_high - y_low))
    used_width = (x_high - x_low) * scale
    used_height = (y_high - y_low) * scale
    origin_x = left + (right - left - used_width) / 2.0
    origin_y = top + (bottom - top - used_height) / 2.0
    return OverviewProjection(origin_x=origin_x, origin_y=origin_y, x_low=x_low, y_low=y_low, scale=scale)


def _project_overview(
    point: WorkoutPointRecord,
    projection: OverviewProjection,
) -> tuple[int, int]:
    x, y = _mercator_xy(float(point.latitude), float(point.longitude))
    px = int(round(projection.origin_x + (x - projection.x_low) * projection.scale))
    py = int(round(projection.origin_y + (y - projection.y_low) * projection.scale))
    return px, py


def _thin_points(points: tuple[WorkoutPointRecord, ...], *, max_points: int) -> tuple[WorkoutPointRecord, ...]:
    if len(points) <= max_points:
        return points
    step = max(1, math.ceil(len(points) / max_points))
    thinned = points[::step]
    if thinned[-1] is not points[-1]:
        thinned = (*thinned, points[-1])
    return thinned


def _draw_background(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    draw.rectangle((0, 0, width, height), fill=(11, 18, 32, 255))
    draw.rectangle((0, 0, width, height), outline=(70, 82, 101, 180), width=2)


def _auto_zoom_request(
    points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    request: OverlayAnimationRequest,
) -> OverlayAnimationRequest:
    if not request.auto_zoom:
        return request
    pace = _local_pace_s_per_km(points, current, sample_s=request.auto_zoom_sample_s)
    if pace is None:
        return request
    fast = min(request.auto_zoom_fast_pace_s_per_km, request.auto_zoom_slow_pace_s_per_km)
    slow = max(request.auto_zoom_fast_pace_s_per_km, request.auto_zoom_slow_pace_s_per_km)
    if slow <= fast:
        return request
    slow_factor = _clamp((pace - fast) / (slow - fast), 0.0, 1.0)
    radius_min = min(request.radius_km, max(0.04, request.radius_min_km))
    tail_min = min(request.tail_km, max(0.02, request.tail_min_km))
    return replace(
        request,
        radius_km=request.radius_km - (request.radius_km - radius_min) * slow_factor,
        tail_km=request.tail_km - (request.tail_km - tail_min) * slow_factor if request.tail_mode == "distance" else request.tail_km,
    )


def _local_pace_s_per_km(
    points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    *,
    sample_s: float,
) -> float | None:
    if current.elapsed_s is not None:
        timeline = tuple(point for point in points if point.elapsed_s is not None and point.distance_km is not None)
        if len(timeline) >= 2:
            half_window = max(2.0, sample_s / 2.0)
            current_elapsed = float(current.elapsed_s)
            before = _point_at_elapsed(timeline, max(float(timeline[0].elapsed_s or 0.0), current_elapsed - half_window))
            after = _point_at_elapsed(timeline, min(float(timeline[-1].elapsed_s or current_elapsed), current_elapsed + half_window))
            if before.distance_km is not None and after.distance_km is not None and after.elapsed_s is not None and before.elapsed_s is not None:
                elapsed = float(after.elapsed_s) - float(before.elapsed_s)
                distance = float(after.distance_km) - float(before.distance_km)
                if elapsed > 0 and distance > 0.00001:
                    return elapsed / distance
    if current.pace_s_per_km is not None and current.pace_s_per_km > 0:
        return float(current.pace_s_per_km)
    return None


def _draw_route_map(
    draw: ImageDraw.ImageDraw,
    segment: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    width: int,
    height: int,
) -> None:
    panel = (16, 54, max(180, int(width * 0.62)), height - 16)
    draw.rounded_rectangle(panel, radius=10, fill=(18, 28, 45, 235), outline=(65, 83, 112, 220), width=2)
    route = tuple(_project(point, segment, panel) for point in segment if point.latitude is not None and point.longitude is not None)
    if len(route) >= 2:
        for first, second in zip(route, route[1:]):
            draw.line((first, second), fill=(76, 146, 255, 235), width=5)
    current_xy = _project(current, segment, panel)
    draw.ellipse(
        (current_xy[0] - 9, current_xy[1] - 9, current_xy[0] + 9, current_xy[1] + 9),
        fill=(245, 158, 11, 255),
        outline=(255, 255, 255, 255),
        width=3,
    )


def _draw_local_route_map(
    draw: ImageDraw.ImageDraw,
    route_points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    width: int,
    height: int,
    request: OverlayAnimationRequest,
) -> None:
    panel = _map_panel(width, height, request)
    if not request.transparent:
        draw.rounded_rectangle(panel, radius=10, fill=(18, 28, 45, 235), outline=(65, 83, 112, 220), width=2)
    current_km = float(current.distance_km or 0.0)
    tail_start = _tail_start_km(route_points, current, request)
    route_end = current_km + max(request.lookahead_km, request.radius_km)
    local_start = max(0.0, current_km - max(request.tail_km, request.radius_km))
    local_end = current_km + max(request.lookahead_km, request.radius_km)
    local_segment = _segment_points(route_points, local_start, local_end)
    center = _point_at_distance(route_points, current_km + request.lookahead_km * 0.5)
    upcoming = _distance_segment_points(route_points, current_km, route_end)
    completed = _distance_segment_points(route_points, tail_start, current_km)
    full_local = _distance_segment_points(route_points, local_start, route_end)
    _draw_projected_line(draw, full_local, center, panel, request, fill=(73, 93, 122, 180), width=4)
    _draw_projected_line(draw, upcoming, center, panel, request, fill=(148, 163, 184, 175), width=4)
    _draw_projected_line(draw, completed, center, panel, request, fill=(76, 146, 255, 245), width=6)
    current_xy = _project_local(current, center, panel, request)
    draw.ellipse(
        (current_xy[0] - 10, current_xy[1] - 10, current_xy[0] + 10, current_xy[1] + 10),
        fill=(245, 158, 11, 255),
        outline=(255, 255, 255, 255),
        width=3,
    )
    if current.distance_km is not None:
        label = f"{float(current.distance_km):.2f} km"
        draw.rounded_rectangle((panel[0] + 12, panel[1] + 12, panel[0] + 92, panel[1] + 38), radius=7, fill=(15, 23, 42, 170 if request.transparent else 210))
        draw.text((panel[0] + 22, panel[1] + 18), label, font=_font(12), fill=(248, 250, 252, 255))


def _draw_circle_route_map(
    image: Image.Image,
    route_points: tuple[WorkoutPointRecord, ...],
    current: WorkoutPointRecord,
    request: OverlayAnimationRequest,
    tile_context: dict[str, Any] | None,
) -> None:
    diameter = max(120, min(request.width - 24, request.height - (82 if request.compass else 24)))
    left = (request.width - diameter) // 2
    top = 12
    circle_fill = (0, 0, 0, 0) if request.map_mode == "tiles" and request.transparent else (18, 28, 45, 235)
    circle = Image.new("RGBA", (diameter, diameter), circle_fill)
    camera: OverlayCamera | None = None
    if request.map_mode == "tiles":
        rendered_tiles = _circle_tile_background(current, diameter, request, tile_context)
        if rendered_tiles is not None:
            tile_background, camera = rendered_tiles
            circle.alpha_composite(tile_background)
        else:
            _draw_schematic_circle_background(circle)
    else:
        _draw_schematic_circle_background(circle)
    if camera is None:
        camera = _overlay_camera(current, diameter, request, tile_size=256)

    circle_draw = ImageDraw.Draw(circle, "RGBA")
    current_km = float(current.distance_km or 0.0)
    tail_start = _tail_start_km(route_points, current, request)
    local_start = max(0.0, current_km - max(request.tail_km, request.radius_km * 1.75))
    local_end = current_km + max(request.lookahead_km, request.radius_km * 1.5)
    visible_route = _distance_segment_points(route_points, local_start, local_end)
    upcoming = _distance_segment_points(route_points, current_km, local_end)
    completed = _distance_segment_points(route_points, tail_start, current_km)
    _draw_circle_projected_line(circle_draw, visible_route, camera, fill=(255, 255, 255, 130), width=4)
    _draw_circle_projected_line(circle_draw, upcoming, camera, fill=(255, 255, 255, 235), width=5)
    _draw_circle_projected_line(circle_draw, completed, camera, fill=(37, 99, 235, 255), width=7)
    current_xy = (diameter // 2, diameter // 2)
    circle_draw.ellipse(
        (current_xy[0] - 10, current_xy[1] - 10, current_xy[0] + 10, current_xy[1] + 10),
        fill=(245, 158, 11, 255),
        outline=(255, 255, 255, 255),
        width=3,
    )

    mask = Image.new("L", (diameter, diameter), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
    image.alpha_composite(Image.composite(circle, Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0)), mask), dest=(left, top))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((left, top, left + diameter - 1, top + diameter - 1), outline=(248, 250, 252, 235), width=4)
    if request.compass:
        heading = _route_heading_at_distance(route_points, current_km)
        _draw_compass_tape(draw, left, top + diameter + 12, diameter, heading)


def _draw_schematic_circle_background(circle: Image.Image) -> None:
    draw = ImageDraw.Draw(circle, "RGBA")
    width, height = circle.size
    draw.rectangle((0, 0, width, height), fill=(18, 28, 45, 235))
    for offset in range(-height, width, 42):
        draw.line((offset, height, offset + height, 0), fill=(51, 65, 85, 95), width=1)


def _circle_tile_background(
    current: WorkoutPointRecord,
    diameter: int,
    request: OverlayAnimationRequest,
    tile_context: dict[str, Any] | None,
) -> tuple[Image.Image, OverlayCamera] | None:
    if tile_context is None or current.latitude is None or current.longitude is None:
        return None
    providers = tile_context.get("providers", ())
    if not providers:
        tile_context["tile_status"] = "disabled"
        return None
    for provider in providers:
        if not isinstance(provider, TileProvider):
            continue
        tile_context["provider"] = provider
        rendered = _circle_tile_background_for_provider(current, diameter, request, tile_context, provider)
        if rendered is not None:
            tile_context["provider"] = provider
            return rendered
    return None


def _circle_tile_background_for_provider(
    current: WorkoutPointRecord,
    diameter: int,
    request: OverlayAnimationRequest,
    tile_context: dict[str, Any],
    provider: TileProvider,
) -> tuple[Image.Image, OverlayCamera] | None:
    camera = _overlay_camera(current, diameter, request, tile_size=provider.tile_size)
    coords = _tile_coords_for_pixel_rect(
        float(camera.render_world_left),
        float(camera.render_world_top),
        diameter,
        diameter,
        camera.zoom,
        provider.tile_size,
    )
    if len(coords) > provider.config.max_tiles:
        tile_context["tile_status"] = "too_many_tiles"
        return None
    provider_cache: dict[str, dict[TileCoord, TileImage]] = tile_context.setdefault("tiles", {})
    cache = provider_cache.setdefault(provider.name, {})
    missing = tuple(coord for coord in coords if coord not in cache)
    if missing:
        try:
            result = fetch_tiles(missing, provider.config)
        except TileFetchError as exc:
            tile_context["tile_status"] = "fetch_failed"
            tile_context["tile_error"] = str(exc)
            return None
        for tile in result.tiles:
            cache[tile.coord] = tile
        tile_context.setdefault("tile_sources", []).extend(tile.source for tile in result.tiles)
    background = Image.new("RGBA", (diameter, diameter), (18, 28, 45, 255))
    for coord in coords:
        tile = cache.get(coord)
        if tile is None:
            continue
        try:
            tile_image = Image.open(BytesIO(tile.content)).convert("RGBA").resize((provider.tile_size, provider.tile_size))
        except OSError:
            continue
        x = coord.x * provider.tile_size - camera.render_world_left
        y = coord.y * provider.tile_size - camera.render_world_top
        background.alpha_composite(tile_image, dest=(x, y))
    overlay = Image.new("RGBA", background.size, (15, 23, 42, 70))
    background.alpha_composite(overlay)
    background = _enhance_tile_background(background)
    background = _with_layer_alpha(background, request.tile_alpha)
    tile_context["tile_status"] = "ok"
    tile_context["provider"] = provider
    tile_context["tile_zoom"] = camera.zoom
    tile_context["tile_count"] = len(cache)
    return background, camera


def _draw_circle_projected_line(
    draw: ImageDraw.ImageDraw,
    points: tuple[WorkoutPointRecord, ...],
    camera: OverlayCamera,
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    route = tuple(_project_circle(point, camera) for point in points if point.latitude is not None and point.longitude is not None)
    if len(route) >= 2:
        for first, second in zip(route, route[1:]):
            draw.line((first, second), fill=fill, width=width)


def _project_circle(
    point: WorkoutPointRecord,
    camera: OverlayCamera,
) -> tuple[int, int]:
    point_x, point_y = _world_pixel(point, camera.zoom, camera.tile_size)
    return int(round(point_x - camera.render_world_left)), int(round(point_y - camera.render_world_top))


def _draw_compass_tape(draw: ImageDraw.ImageDraw, left: int, top: int, width: int, heading: float | None) -> None:
    heading = heading or 0.0
    tape_width = width
    tape_left = left
    tape_right = tape_left + tape_width
    center = (tape_left + tape_right) // 2
    y = top + 17
    draw.rounded_rectangle((tape_left, top, tape_right, top + 40), radius=20, fill=(15, 23, 42, 175), outline=(248, 250, 252, 220), width=2)
    draw.line((tape_left + 18, y, tape_right - 18, y), fill=(248, 250, 252, 210), width=2)
    draw.polygon(((center, top + 5), (center - 6, top + 16), (center + 6, top + 16)), fill=(245, 158, 11, 255))
    font = _font(14)
    for label, bearing in (("N", 0.0), ("E", 90.0), ("S", 180.0), ("W", 270.0)):
        delta = _angle_delta(bearing, heading)
        x = center + int(delta / 90.0 * (tape_width * 0.34))
        if tape_left + 20 <= x <= tape_right - 20:
            draw.line((x, y - 9, x, y), fill=(248, 250, 252, 225), width=2)
            draw.text((x - 5, y + 4), label, font=font, fill=(248, 250, 252, 255))


def _route_heading_at_distance(points: tuple[WorkoutPointRecord, ...], current_km: float) -> float | None:
    sample_km = 0.02
    ahead = _point_at_distance(points, current_km + sample_km)
    current = _point_at_distance(points, current_km)
    heading = _bearing(current, ahead)
    if heading is not None:
        return heading
    behind = _point_at_distance(points, max(0.0, current_km - sample_km))
    return _bearing(behind, current)


def _bearing(first: WorkoutPointRecord, second: WorkoutPointRecord) -> float | None:
    if first.latitude is None or first.longitude is None or second.latitude is None or second.longitude is None:
        return None
    lat1 = math.radians(float(first.latitude))
    lat2 = math.radians(float(second.latitude))
    delta_lon = math.radians(float(second.longitude) - float(first.longitude))
    y = math.sin(delta_lon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def _angle_delta(bearing: float, heading: float) -> float:
    return ((bearing - heading + 540.0) % 360.0) - 180.0


def _map_panel(width: int, height: int, request: OverlayAnimationRequest) -> tuple[int, int, int, int]:
    if request.show_map and not request.show_speed and not request.show_hr:
        return (8, 8, width - 8, height - 8)
    return (16, 54, max(180, int(width * 0.62)), height - 16)


def _draw_projected_line(
    draw: ImageDraw.ImageDraw,
    points: tuple[WorkoutPointRecord, ...],
    center: WorkoutPointRecord,
    panel: tuple[int, int, int, int],
    request: OverlayAnimationRequest,
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    route = tuple(_project_local(point, center, panel, request) for point in points if point.latitude is not None and point.longitude is not None)
    if len(route) >= 2:
        for first, second in zip(route, route[1:]):
            draw.line((first, second), fill=fill, width=width)


def _project_local(
    point: WorkoutPointRecord,
    center: WorkoutPointRecord,
    panel: tuple[int, int, int, int],
    request: OverlayAnimationRequest,
) -> tuple[int, int]:
    point_x, point_y = _mercator_xy(float(point.latitude), float(point.longitude))
    center_x, center_y = _mercator_xy(float(center.latitude), float(center.longitude))
    left, top, right, bottom = panel
    inner_width = max(1, right - left - 28)
    inner_height = max(1, bottom - top - 28)
    radius_world = max(40.0, request.radius_km * 1000.0) / EARTH_CIRCUMFERENCE_M
    aspect = inner_width / max(1, inner_height)
    x_span = radius_world * 2.0 * max(1.0, aspect)
    y_span = radius_world * 2.0
    px = left + 14 + int((0.5 + (point_x - center_x) / x_span) * inner_width)
    py = top + 14 + int((0.5 + (point_y - center_y) / y_span) * inner_height)
    return px, py


def _tile_context(tile_cache_root: Path | None, maps_config: MapsConfig | None, *, map_style: str = "streets-v2-dark") -> dict[str, Any]:
    if tile_cache_root is None:
        return {"tile_status": "disabled"}
    providers = _tile_providers(tile_cache_root, maps_config, map_style=map_style)
    return {"providers": providers, "provider": providers[0] if providers else None, "tile_status": "disabled"}


def _tile_providers(tile_cache_root: Path, maps_config: MapsConfig | None, *, map_style: str = "streets-v2-dark") -> tuple[TileProvider, ...]:
    providers: list[TileProvider] = []
    if maps_config is not None and maps_config.provider == "maptiler" and maps_config.maptiler_api_key:
        map_id = _maptiler_overlay_map_id(map_style, maps_config.maptiler_map_id)
        providers.append(
            TileProvider(
                name="maptiler",
                background="maptiler_tiles",
                attribution="MapTiler / OpenStreetMap contributors",
                tile_size=512,
                config=TileFetchConfig(
                    cache_root=tile_cache_root.parent / "maptiler_tiles" / map_id,
                    url_template=f"https://api.maptiler.com/maps/{map_id}/{{z}}/{{x}}/{{y}}.png?key={maps_config.maptiler_api_key}",
                    timeout_s=maps_config.timeout_s,
                    max_tiles=96,
                ),
            )
        )
    providers.append(
        TileProvider(
            name="openstreetmap",
            background="osm",
            attribution=DEFAULT_OSM_ATTRIBUTION,
            tile_size=256,
            config=TileFetchConfig(cache_root=tile_cache_root, max_tiles=96),
        )
    )
    return tuple(providers)


def _maptiler_overlay_map_id(map_style: str, fallback: str) -> str:
    normalized = map_style.strip().lower().replace("_", "-")
    aliases = {
        "dark": "streets-v2-dark",
        "streets-dark": "streets-v2-dark",
        "streets-v2-dark": "streets-v2-dark",
        "streets-v4-dark": "streets-v4-dark",
        "outdoor-dark": "outdoor-v2-dark",
        "outdoor-v2-dark": "outdoor-v2-dark",
        "outdoors-dark": "outdoor-v2-dark",
        "outdoor": "outdoor-v2",
        "outdoor-v2": "outdoor-v2",
        "outdoors": "outdoor-v2",
        "dataviz-dark": "dataviz-dark",
        "light": "dataviz-light",
        "dataviz-light": "dataviz-light",
        "dataviz": "dataviz",
        "streets": "streets-v4",
        "streets-v4": "streets-v4",
        "streets-v2": "streets-v2",
        "basic-dark": "basic-v2-dark",
        "basic-v2-dark": "basic-v2-dark",
        "basic": "basic-v2",
        "basic-v2": "basic-v2",
    }
    if normalized in aliases:
        return aliases[normalized]
    return fallback or "streets-v2-dark"


def _with_layer_alpha(image: Image.Image, alpha: float) -> Image.Image:
    alpha = max(0.0, min(1.0, alpha))
    if alpha >= 0.999:
        return image
    output = image.copy()
    current_alpha = output.getchannel("A")
    scaled_alpha = current_alpha.point(lambda value: int(round(value * alpha)))
    output.putalpha(scaled_alpha)
    return output


def _enhance_tile_background(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    rgb = image.convert("RGB")
    rgb = ImageEnhance.Contrast(rgb).enhance(1.18)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.12)
    output = rgb.convert("RGBA").filter(ImageFilter.UnsharpMask(radius=1.1, percent=70, threshold=3))
    output.putalpha(alpha)
    return output


def _tile_metadata(tile_context: dict[str, Any] | None) -> dict[str, object]:
    if tile_context is None:
        return {}
    provider = tile_context.get("provider")
    metadata: dict[str, object] = {
        "map_background": getattr(provider, "background", "plain"),
        "tile_status": tile_context.get("tile_status", "disabled"),
    }
    if isinstance(provider, TileProvider):
        metadata.update(
            {
                "tile_provider": provider.name,
                "tile_attribution": provider.attribution,
                "tile_size": provider.tile_size,
            }
        )
    if tile_context.get("tile_zoom") is not None:
        metadata["tile_zoom"] = tile_context["tile_zoom"]
    if tile_context.get("tile_count") is not None:
        metadata["tile_count"] = tile_context["tile_count"]
    if tile_context.get("tile_sources"):
        metadata["tile_sources"] = list(tile_context["tile_sources"])
    if tile_context.get("tile_error"):
        metadata["tile_error"] = tile_context["tile_error"]
    return metadata


def _circle_zoom(
    current: WorkoutPointRecord,
    diameter: int,
    request: OverlayAnimationRequest,
    *,
    tile_size: int,
) -> int:
    latitude = float(current.latitude or 0.0)
    meters_per_pixel = max(0.1, (request.radius_km * 2000.0) / max(1, diameter))
    raw = math.log2(max(1.0, math.cos(math.radians(latitude)) * EARTH_CIRCUMFERENCE_M / (tile_size * meters_per_pixel)))
    return max(1, min(19, int(round(raw))))


def _overlay_camera(
    current: WorkoutPointRecord,
    diameter: int,
    request: OverlayAnimationRequest,
    *,
    tile_size: int,
) -> OverlayCamera:
    zoom = _circle_zoom(current, diameter, request, tile_size=tile_size)
    center_x, center_y = _world_pixel(current, zoom, tile_size)
    world_left = center_x - diameter / 2.0
    world_top = center_y - diameter / 2.0
    return OverlayCamera(
        center=current,
        zoom=zoom,
        tile_size=tile_size,
        diameter=diameter,
        world_left=world_left,
        world_top=world_top,
        render_world_left=int(round(world_left)),
        render_world_top=int(round(world_top)),
    )


def _world_pixel(point: WorkoutPointRecord, zoom: int, tile_size: int) -> tuple[float, float]:
    x, y = _mercator_xy(float(point.latitude), float(point.longitude))
    scale = float((2**zoom) * tile_size)
    return x * scale, y * scale


def _tile_coords_for_pixel_rect(left: float, top: float, width: int, height: int, zoom: int, tile_size: int) -> tuple[TileCoord, ...]:
    n = 2**zoom
    x_min = max(0, min(n - 1, math.floor(left / tile_size)))
    x_max = max(0, min(n - 1, math.floor((left + width - 1) / tile_size)))
    y_min = max(0, min(n - 1, math.floor(top / tile_size)))
    y_max = max(0, min(n - 1, math.floor((top + height - 1) / tile_size)))
    return tuple(TileCoord(z=zoom, x=x, y=y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1))


def _draw_title(draw: ImageDraw.ImageDraw, workout: WorkoutRecord, start_km: float, end_km: float) -> None:
    font = _font(18)
    small = _font(13)
    title = workout.title or workout.workout_id
    draw.text((18, 14), _ellipsize(title, 34), font=font, fill=(248, 250, 252, 255))
    draw.text((18, 34), f"{start_km:.2f}-{end_km:.2f} km", font=small, fill=(174, 184, 199, 255))


def _draw_speed_gauge(
    draw: ImageDraw.ImageDraw,
    current: WorkoutPointRecord,
    segment: tuple[WorkoutPointRecord, ...],
    width: int,
    height: int,
) -> None:
    panel_height = max(54, min(104, int((height - 72) * 0.46)))
    box = (int(width * 0.66), 58, width - 18, 58 + panel_height)
    if box[2] - box[0] < 80 or box[3] - box[1] < 48:
        return
    draw.rounded_rectangle(box, radius=10, fill=(248, 250, 252, 238), outline=(203, 213, 225, 255), width=2)
    pace = current.pace_s_per_km or _derived_pace(current, segment)
    label = "-- /km" if pace is None else f"{_format_pace(pace)} /km"
    speed = "" if pace is None or pace <= 0 else f"{3600.0 / pace:.1f} km/h"
    draw.text((box[0] + 14, box[1] + 12), "PACE", font=_font(13), fill=(71, 85, 105, 255))
    draw.text((box[0] + 14, box[1] + 32), label, font=_font(22 if box[2] - box[0] < 150 else 28), fill=(15, 23, 42, 255))
    if speed and box[3] - box[1] >= 86:
        draw.text((box[0] + 15, box[1] + 75), speed, font=_font(15), fill=(71, 85, 105, 255))


def _draw_hr_gauge(draw: ImageDraw.ImageDraw, current: WorkoutPointRecord, width: int, height: int) -> None:
    top = max(118, int(height * 0.66))
    box = (int(width * 0.66), top, width - 18, height - 18)
    if box[2] - box[0] < 80 or box[3] - box[1] < 48:
        return
    draw.rounded_rectangle(box, radius=10, fill=(248, 250, 252, 238), outline=(203, 213, 225, 255), width=2)
    hr = current.heart_rate_bpm
    value = "--" if hr is None else str(int(round(hr)))
    draw.text((box[0] + 14, box[1] + 12), "HR", font=_font(13), fill=(71, 85, 105, 255))
    draw.text((box[0] + 14, box[1] + 32), value, font=_font(24 if box[2] - box[0] < 150 else 32), fill=(185, 28, 28, 255))
    if box[2] - box[0] >= 120:
        draw.text((box[0] + 70, box[1] + 42), "bpm", font=_font(14), fill=(71, 85, 105, 255))


def _point_at_progress(segment: tuple[WorkoutPointRecord, ...], progress: float) -> WorkoutPointRecord:
    distances = tuple(float(point.distance_km or 0.0) for point in segment)
    low, high = min(distances), max(distances)
    target = low + (high - low) * max(0.0, min(1.0, progress))
    return min(segment, key=lambda point: abs(float(point.distance_km or 0.0) - target))


def _point_at_distance(points: tuple[WorkoutPointRecord, ...], target_km: float) -> WorkoutPointRecord:
    distance_points = tuple(point for point in points if point.distance_km is not None and point.latitude is not None and point.longitude is not None)
    if len(distance_points) < 2:
        return distance_points[0]
    if target_km <= float(distance_points[0].distance_km or 0.0):
        return distance_points[0]
    for first, second in zip(distance_points, distance_points[1:]):
        first_distance = float(first.distance_km or 0.0)
        second_distance = float(second.distance_km or 0.0)
        if first_distance <= target_km <= second_distance and second_distance > first_distance:
            return _interpolate_point(first, second, (target_km - first_distance) / (second_distance - first_distance))
    return distance_points[-1]


def _elapsed_at_distance(points: tuple[WorkoutPointRecord, ...], target_km: float) -> float:
    if target_km <= float(points[0].distance_km or 0.0):
        return float(points[0].elapsed_s or 0.0)
    for first, second in zip(points, points[1:]):
        if first.distance_km is None or second.distance_km is None or first.elapsed_s is None or second.elapsed_s is None:
            continue
        first_distance = float(first.distance_km)
        second_distance = float(second.distance_km)
        if first_distance <= target_km <= second_distance and second_distance > first_distance:
            ratio = (target_km - first_distance) / (second_distance - first_distance)
            return float(first.elapsed_s) + (float(second.elapsed_s) - float(first.elapsed_s)) * ratio
    return float(points[-1].elapsed_s or 0.0)


def _point_at_elapsed(points: tuple[WorkoutPointRecord, ...], target_elapsed_s: float) -> WorkoutPointRecord:
    if target_elapsed_s <= float(points[0].elapsed_s or 0.0):
        return points[0]
    for first, second in zip(points, points[1:]):
        if first.elapsed_s is None or second.elapsed_s is None:
            continue
        first_elapsed = float(first.elapsed_s)
        second_elapsed = float(second.elapsed_s)
        if first_elapsed <= target_elapsed_s <= second_elapsed and second_elapsed > first_elapsed:
            return _interpolate_point(first, second, (target_elapsed_s - first_elapsed) / (second_elapsed - first_elapsed))
    return points[-1]


def _interpolate_point(first: WorkoutPointRecord, second: WorkoutPointRecord, ratio: float) -> WorkoutPointRecord:
    ratio = max(0.0, min(1.0, ratio))
    return replace(
        first,
        latitude=_lerp_optional(first.latitude, second.latitude, ratio),
        longitude=_lerp_optional(first.longitude, second.longitude, ratio),
        elevation_m=_lerp_optional(first.elevation_m, second.elevation_m, ratio),
        elapsed_s=_lerp_optional(first.elapsed_s, second.elapsed_s, ratio),
        distance_m=_lerp_optional(first.distance_m, second.distance_m, ratio),
        distance_km=_lerp_optional(first.distance_km, second.distance_km, ratio),
        heart_rate_bpm=_lerp_optional(first.heart_rate_bpm, second.heart_rate_bpm, ratio),
        cadence_spm=_lerp_optional(first.cadence_spm, second.cadence_spm, ratio),
        pace_s_per_km=_lerp_optional(first.pace_s_per_km, second.pace_s_per_km, ratio),
    )


def _lerp_optional(first: float | None, second: float | None, ratio: float) -> float | None:
    if first is None or second is None:
        return first if ratio < 0.5 else second
    return float(first) + (float(second) - float(first)) * ratio


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _project(
    point: WorkoutPointRecord,
    segment: tuple[WorkoutPointRecord, ...],
    panel: tuple[int, int, int, int],
) -> tuple[int, int]:
    projected = tuple(_mercator_xy(float(item.latitude), float(item.longitude)) for item in segment if item.latitude is not None and item.longitude is not None)
    x, y = _mercator_xy(float(point.latitude), float(point.longitude))
    x_values = tuple(item[0] for item in projected)
    y_values = tuple(item[1] for item in projected)
    x_low, x_high = _padded(min(x_values), max(x_values))
    y_low, y_high = _padded(min(y_values), max(y_values))
    left, top, right, bottom = panel
    px = left + 18 + int((x - x_low) / max(0.000001, x_high - x_low) * max(1, right - left - 36))
    py = top + 18 + int((y - y_low) / max(0.000001, y_high - y_low) * max(1, bottom - top - 36))
    return px, py


def _padded(low: float, high: float) -> tuple[float, float]:
    if low == high:
        return low - 0.0001, high + 0.0001
    padding = (high - low) * 0.16
    return low - padding, high + padding


def _derived_pace(current: WorkoutPointRecord, segment: tuple[WorkoutPointRecord, ...]) -> float | None:
    if current.distance_km is None:
        return None
    index = min(
        range(len(segment)),
        key=lambda candidate: abs(float(segment[candidate].distance_km or 0.0) - float(current.distance_km or 0.0)),
    )
    first = segment[max(0, index - 2)]
    last = segment[min(len(segment) - 1, index + 2)]
    if first.elapsed_s is None or last.elapsed_s is None or first.distance_km is None or last.distance_km is None:
        return None
    elapsed = float(last.elapsed_s) - float(first.elapsed_s)
    distance = float(last.distance_km) - float(first.distance_km)
    if elapsed <= 0 or distance <= 0:
        return None
    return elapsed / distance


def _format_pace(seconds: float) -> str:
    total = max(1, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    return f"{minutes}:{secs:02d}"


def _encoded_frames(
    frames: list[Image.Image],
    *,
    output_format: str,
    fps: int,
    duration_ms: int,
) -> tuple[bytes, str, str]:
    if output_format == "webm":
        return _webm_bytes(frames, fps=fps), "webm", "video/webm"
    if output_format == "mov":
        return _mov_bytes(frames, fps=fps), "mov", "video/quicktime"
    if output_format == "mp4":
        return _mp4_bytes(frames, fps=fps), "mp4", "video/mp4"
    return _gif_bytes(frames, duration_ms=duration_ms), "gif", "image/gif"


def _gif_bytes(frames: list[Image.Image], *, duration_ms: int) -> bytes:
    output = BytesIO()
    gif_frames = [frame.convert("RGB") for frame in frames]
    gif_frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=gif_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    return output.getvalue()


def _webm_bytes(frames: list[Image.Image], *, fps: int) -> bytes:
    width, height = frames[0].size
    return _ffmpeg_rawvideo_bytes(
        frames,
        fps=fps,
        args=[
            "-c:v",
            "libvpx-vp9",
            "-pix_fmt",
            "yuva420p",
            "-auto-alt-ref",
            "0",
            "-b:v",
            "0",
            "-crf",
            "30",
            "-f",
            "webm",
            "pipe:1",
        ],
        input_size=(width, height),
    )


def _mov_bytes(frames: list[Image.Image], *, fps: int) -> bytes:
    width, height = frames[0].size
    return _ffmpeg_rawvideo_bytes(
        frames,
        fps=fps,
        args=[
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            "-vendor",
            "apl0",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mov",
            "pipe:1",
        ],
        input_size=(width, height),
    )


def _mp4_bytes(frames: list[Image.Image], *, fps: int) -> bytes:
    width, height = frames[0].size
    return _ffmpeg_rawvideo_bytes(
        [frame.convert("RGB") for frame in frames],
        fps=fps,
        args=[
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-movflags",
            "frag_keyframe+empty_moov",
            "-f",
            "mp4",
            "pipe:1",
        ],
        input_size=(width, height),
        input_pix_fmt="rgb24",
    )


def _ffmpeg_rawvideo_bytes(
    frames: list[Image.Image],
    *,
    fps: int,
    args: list[str],
    input_size: tuple[int, int],
    input_pix_fmt: str = "rgba",
) -> bytes:
    if not frames:
        raise OverlayAnimationEncodingError("no frames to encode")
    ffmpeg = _ffmpeg_executable()
    if ffmpeg is None:
        raise OverlayAnimationEncoderUnavailableError("ffmpeg is not installed")
    width, height = input_size
    command = [
        ffmpeg,
        "-v",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        input_pix_fmt,
        "-s",
        f"{width}x{height}",
        "-r",
        str(max(1, fps)),
        "-i",
        "pipe:0",
        "-an",
    ]
    if not args or args[-1] != "pipe:1":
        raise OverlayAnimationEncodingError("ffmpeg output arguments must end with pipe:1")
    output_suffix = f".{args[-2]}" if len(args) >= 2 and args[-2] in {"mov", "mp4", "webm"} else ".video"
    fd, raw_output_path = tempfile.mkstemp(prefix="aimo-overlay-", suffix=output_suffix)
    os.close(fd)
    Path(raw_output_path).unlink(missing_ok=True)
    output_path = Path(raw_output_path)
    command.extend(args[:-1])
    command.append(str(output_path))
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None
    try:
        for frame in frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        process.stdin = None
        _, stderr = process.communicate()
    except BrokenPipeError as exc:
        process.kill()
        _, stderr = process.communicate()
        output_path.unlink(missing_ok=True)
        raise OverlayAnimationEncodingError(stderr.decode("utf-8", errors="replace") or str(exc)) from exc
    except ValueError as exc:
        process.kill()
        _, stderr = process.communicate()
        output_path.unlink(missing_ok=True)
        raise OverlayAnimationEncodingError(stderr.decode("utf-8", errors="replace") or str(exc)) from exc
    if process.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise OverlayAnimationEncodingError(stderr.decode("utf-8", errors="replace") or "ffmpeg encoding failed")
    try:
        return output_path.read_bytes()
    finally:
        output_path.unlink(missing_ok=True)


def _ffmpeg_executable() -> str | None:
    if executable := shutil.which("ffmpeg"):
        return executable
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _ellipsize(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)] + "..."


def _overlay_filename(workout: WorkoutRecord, start_km: float, end_km: float, overlay_type: str, extension: str) -> str:
    title = workout.title or workout.workout_id
    date = workout.local_date or (workout.start_time_local or workout.start_time_utc or "")[:10] or "no-date"
    distance = f"{start_km:.2f}-{end_km:.2f}km"
    return f"{_safe_filename(title)}_{_safe_filename(date)}_{distance}_{_safe_filename(overlay_type)}.{extension}"


def _safe_filename(value: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "workout"
