from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ASCENT_DEADBAND_M = 3.0
LOCAL_TIMEZONE = "Europe/Helsinki"


class GpxParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedGpxPoint:
    point_index: int
    segment_index: int
    latitude: float | None = None
    longitude: float | None = None
    elevation_m: float | None = None
    timestamp_utc: str | None = None
    elapsed_s: float | None = None
    distance_m: float | None = None
    distance_km: float | None = None
    heart_rate_bpm: float | None = None
    cadence_spm: float | None = None
    pace_s_per_km: float | None = None


@dataclass(frozen=True)
class ParsedGpxStream:
    stream_key: str
    unit: str
    sample_count: int
    min_value: float | None = None
    max_value: float | None = None
    avg_value: float | None = None


@dataclass(frozen=True)
class ParsedGpxWorkout:
    title: str
    kind: str
    primary_kind: str
    start_time_utc: str | None
    start_time_local: str | None
    local_date: str | None
    distance_km: float | None
    duration_s: float | None
    pace_s_per_km: float | None
    ascent_m: float | None
    avg_hr_bpm: float | None
    max_hr_bpm: float | None
    points: tuple[ParsedGpxPoint, ...]
    streams: tuple[ParsedGpxStream, ...]
    metadata: dict[str, object] = field(default_factory=dict)


def parse_gpx(content: bytes, *, fallback_title: str = "Workout") -> ParsedGpxWorkout:
    if not content:
        raise GpxParseError("GPX content is empty")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise GpxParseError("GPX XML did not parse") from exc
    if _local_name(root.tag) != "gpx":
        raise GpxParseError("XML root is not gpx")

    title = _first_text(root, ("metadata/name", "trk/name", "rte/name")) or _title_from_filename(fallback_title)
    track_points = _collect_points(root, container_name="trkseg", point_name="trkpt")
    route_points = _collect_points(root, container_name="rte", point_name="rtept")
    waypoint_points = _collect_points(root, container_name="gpx", point_name="wpt")
    raw_points = track_points + route_points + waypoint_points
    if not raw_points:
        raise GpxParseError("GPX contains no usable points")

    points = _derive_points(raw_points)
    timestamps = [_parse_time(point.timestamp_utc) for point in points if point.timestamp_utc]
    timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
    heart_rates = [point.heart_rate_bpm for point in points if point.heart_rate_bpm is not None]
    cadences = [point.cadence_spm for point in points if point.cadence_spm is not None]
    elevations = [point.elevation_m for point in points if point.elevation_m is not None]
    distances = [point.distance_m for point in points if point.distance_m is not None]
    total_distance_m = distances[-1] if distances else None
    duration_s = (timestamps[-1] - timestamps[0]).total_seconds() if len(timestamps) >= 2 else None
    pace_s_per_km = (
        duration_s / (total_distance_m / 1000)
        if duration_s is not None and total_distance_m is not None and total_distance_m > 0
        else None
    )
    start_time = timestamps[0] if timestamps else None
    kind, primary_kind = _classify(
        has_activity=bool(timestamps or heart_rates or cadences),
        has_track=bool(track_points),
        has_route=bool(route_points or waypoint_points),
    )

    streams = tuple(
        stream
        for stream in (
            _stream("distance", "m", distances),
            _stream("elevation", "m", elevations),
            _stream("heart_rate", "bpm", heart_rates),
            _stream("cadence", "spm", cadences),
            _stream("pace", "s/km", [point.pace_s_per_km for point in points if point.pace_s_per_km is not None]),
        )
        if stream is not None
    )

    return ParsedGpxWorkout(
        title=title,
        kind=kind,
        primary_kind=primary_kind,
        start_time_utc=_format_time(start_time),
        start_time_local=_format_local_time(start_time),
        local_date=_local_date(start_time),
        distance_km=round(total_distance_m / 1000, 3) if total_distance_m is not None else None,
        duration_s=duration_s,
        pace_s_per_km=pace_s_per_km,
        ascent_m=_ascent(points),
        avg_hr_bpm=_avg(heart_rates),
        max_hr_bpm=max(heart_rates) if heart_rates else None,
        points=points,
        streams=streams,
        metadata={
            "track_point_count": len(track_points),
            "route_point_count": len(route_points),
            "waypoint_count": len(waypoint_points),
        },
    )


def _collect_points(root: ElementTree.Element, *, container_name: str, point_name: str) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    segment_index = 0
    if container_name == "gpx":
        containers = [root]
    else:
        containers = [element for element in root.iter() if _local_name(element.tag) == container_name]
    for container in containers:
        current = [
            _raw_point(element, segment_index=segment_index)
            for element in list(container)
            if _local_name(element.tag) == point_name
        ]
        if current:
            points.extend(current)
            segment_index += 1
    return points


def _raw_point(element: ElementTree.Element, *, segment_index: int) -> dict[str, object]:
    return {
        "segment_index": segment_index,
        "latitude": _float(element.attrib.get("lat")),
        "longitude": _float(element.attrib.get("lon")),
        "elevation_m": _float(_child_text(element, "ele")),
        "timestamp_utc": _format_time(_parse_time(_child_text(element, "time"))),
        "heart_rate_bpm": _extension_number(element, {"hr", "heartrate"}),
        "cadence_spm": _extension_number(element, {"cad", "cadence"}),
    }


def _derive_points(raw_points: list[dict[str, object]]) -> tuple[ParsedGpxPoint, ...]:
    points: list[ParsedGpxPoint] = []
    total_distance = 0.0
    first_time: datetime | None = None
    previous_raw: dict[str, object] | None = None
    previous_time: datetime | None = None
    for index, raw in enumerate(raw_points):
        timestamp = _parse_time(raw.get("timestamp_utc") if isinstance(raw.get("timestamp_utc"), str) else None)
        if first_time is None and timestamp is not None:
            first_time = timestamp
        if previous_raw is not None:
            step_distance = _distance_between(previous_raw, raw)
            if step_distance is not None:
                total_distance += step_distance
        pace = None
        if previous_time is not None and timestamp is not None and previous_raw is not None:
            step_distance = _distance_between(previous_raw, raw)
            step_seconds = (timestamp - previous_time).total_seconds()
            if step_distance is not None and step_distance > 0 and step_seconds > 0:
                pace = step_seconds / (step_distance / 1000)
        points.append(
            ParsedGpxPoint(
                point_index=index,
                segment_index=int(raw["segment_index"]),
                latitude=_as_float(raw.get("latitude")),
                longitude=_as_float(raw.get("longitude")),
                elevation_m=_as_float(raw.get("elevation_m")),
                timestamp_utc=_format_time(timestamp),
                elapsed_s=(timestamp - first_time).total_seconds() if timestamp and first_time else None,
                distance_m=total_distance,
                distance_km=total_distance / 1000,
                heart_rate_bpm=_as_float(raw.get("heart_rate_bpm")),
                cadence_spm=_as_float(raw.get("cadence_spm")),
                pace_s_per_km=pace,
            )
        )
        previous_raw = raw
        previous_time = timestamp
    return tuple(points)


def _first_text(root: ElementTree.Element, paths: tuple[str, ...]) -> str:
    for path in paths:
        parts = path.split("/")
        candidates = [root]
        for part in parts:
            next_candidates = []
            for candidate in candidates:
                next_candidates.extend(child for child in candidate if _local_name(child.tag) == part)
            candidates = next_candidates
        for candidate in candidates:
            if candidate.text and candidate.text.strip():
                return candidate.text.strip()
    return ""


def _child_text(element: ElementTree.Element, name: str) -> str:
    for child in element:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return ""


def _extension_number(element: ElementTree.Element, names: set[str]) -> float | None:
    for child in element.iter():
        if _local_name(child.tag).lower() in names and child.text:
            value = _float(child.text)
            if value is not None:
                return value
    return None


def _distance_between(left: dict[str, object], right: dict[str, object]) -> float | None:
    lat1 = _as_float(left.get("latitude"))
    lon1 = _as_float(left.get("longitude"))
    lat2 = _as_float(right.get("latitude"))
    lon2 = _as_float(right.get("longitude"))
    if None in {lat1, lon1, lat2, lon2}:
        return None
    return _haversine_m(lat1, lon1, lat2, lon2)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(a))


def _ascent(points: tuple[ParsedGpxPoint, ...]) -> float | None:
    elevations = [point.elevation_m for point in points if point.elevation_m is not None]
    if not elevations:
        return None

    total = 0.0
    valley = elevations[0]
    peak = elevations[0]
    climbing = False
    for elevation in elevations[1:]:
        if elevation > peak:
            peak = elevation
            if peak - valley >= ASCENT_DEADBAND_M:
                climbing = True
            continue
        if elevation >= peak:
            continue
        if climbing and peak - elevation >= ASCENT_DEADBAND_M:
            total += peak - valley
            valley = elevation
            peak = elevation
            climbing = False
        elif not climbing and elevation < valley:
            valley = elevation
            peak = elevation

    if climbing:
        total += peak - valley
    return total


def _classify(*, has_activity: bool, has_track: bool, has_route: bool) -> tuple[str, str]:
    if has_activity and has_route:
        return "hybrid", "hybrid"
    if has_activity or has_track:
        return "activity", "activity"
    return "route_plan", "route"


def _stream(key: str, unit: str, values: list[float | None]) -> ParsedGpxStream | None:
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return ParsedGpxStream(
        stream_key=key,
        unit=unit,
        sample_count=len(numeric),
        min_value=min(numeric),
        max_value=max(numeric),
        avg_value=_avg(numeric),
    )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_local_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_local_timezone()).isoformat()


def _local_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(_local_timezone()).date().isoformat()


def _local_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(LOCAL_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _title_from_filename(value: str) -> str:
    stem = Path(value).stem.strip()
    return stem or "Workout"


def _float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    return value if isinstance(value, float) else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
