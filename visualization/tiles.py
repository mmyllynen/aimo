from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen


OSM_TILE_URL_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = "\u00a9 OpenStreetMap contributors"
DEFAULT_USER_AGENT = "AimoRoutePlotter/0.1"
DEFAULT_MIN_TTL = timedelta(days=7)
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_TILES = 64
MIN_ZOOM = 0
MAX_ZOOM = 19
WEB_MERCATOR_MAX_LAT = 85.05112878


class TileFetchError(RuntimeError):
    """Raised when tile fetching cannot satisfy deterministic render limits."""


@dataclass(frozen=True, order=True)
class TileCoord:
    z: int
    x: int
    y: int


@dataclass(frozen=True)
class TileImage:
    coord: TileCoord
    content: bytes
    source: str


@dataclass(frozen=True)
class TileFetchResult:
    tiles: tuple[TileImage, ...]
    attribution: str = OSM_ATTRIBUTION
    provider: str = "openstreetmap"


@dataclass(frozen=True)
class TileFetchConfig:
    cache_root: Path
    url_template: str = OSM_TILE_URL_TEMPLATE
    user_agent: str = DEFAULT_USER_AGENT
    min_ttl: timedelta = DEFAULT_MIN_TTL
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_tiles: int = DEFAULT_MAX_TILES
    min_zoom: int = MIN_ZOOM
    max_zoom: int = MAX_ZOOM


class HTTPResponse(Protocol):
    headers: Mapping[str, str]

    def __enter__(self) -> HTTPResponse: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> object: ...

    def read(self) -> bytes: ...


URLOpener = Callable[[Request, float], HTTPResponse]


def tile_url(coord: TileCoord, config: TileFetchConfig) -> str:
    _validate_coord(coord, config)
    return config.url_template.format(z=coord.z, x=coord.x, y=coord.y)


def tile_cache_path(coord: TileCoord, config: TileFetchConfig) -> Path:
    _validate_coord(coord, config)
    return config.cache_root / str(coord.z) / str(coord.x) / f"{coord.y}.png"


def lat_lon_to_tile(latitude: float, longitude: float, zoom: int) -> TileCoord:
    _validate_zoom(zoom)
    lat = min(max(latitude, -WEB_MERCATOR_MAX_LAT), WEB_MERCATOR_MAX_LAT)
    lon = min(max(longitude, -180.0), 180.0)
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return TileCoord(z=zoom, x=_clamp_int(x, 0, n - 1), y=_clamp_int(y, 0, n - 1))


def tile_coords_for_bounds(
    min_latitude: float,
    min_longitude: float,
    max_latitude: float,
    max_longitude: float,
    zoom: int,
) -> tuple[TileCoord, ...]:
    _validate_zoom(zoom)
    west = min(min_longitude, max_longitude)
    east = max(min_longitude, max_longitude)
    south = min(min_latitude, max_latitude)
    north = max(min_latitude, max_latitude)
    top_left = lat_lon_to_tile(north, west, zoom)
    bottom_right = lat_lon_to_tile(south, east, zoom)
    coords: list[TileCoord] = []
    for x in range(top_left.x, bottom_right.x + 1):
        for y in range(top_left.y, bottom_right.y + 1):
            coords.append(TileCoord(z=zoom, x=x, y=y))
    return tuple(coords)


def fetch_tiles(
    coords: tuple[TileCoord, ...],
    config: TileFetchConfig,
    opener: URLOpener = urlopen,
    now: datetime | None = None,
) -> TileFetchResult:
    unique_coords = tuple(sorted(set(coords)))
    if len(unique_coords) > config.max_tiles:
        raise TileFetchError(f"tile count {len(unique_coords)} exceeds limit {config.max_tiles}")
    timestamp = now or datetime.now(UTC)
    tiles = tuple(_fetch_tile(coord, config, opener, timestamp) for coord in unique_coords)
    return TileFetchResult(tiles=tiles)


def _fetch_tile(coord: TileCoord, config: TileFetchConfig, opener: URLOpener, now: datetime) -> TileImage:
    path = tile_cache_path(coord, config)
    metadata_path = _metadata_path(path)
    metadata = _read_metadata(metadata_path)
    if path.exists() and _is_fresh(metadata, now):
        return TileImage(coord=coord, content=path.read_bytes(), source="cache")

    headers = {"User-Agent": config.user_agent}
    if path.exists():
        etag = metadata.get("etag", "")
        last_modified = metadata.get("last_modified", "")
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
    request = Request(tile_url(coord, config), headers=headers)
    try:
        with opener(request, timeout=config.timeout_s) as response:
            content = response.read()
            response_headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
    except HTTPError as exc:
        if exc.code == 304 and path.exists():
            _write_metadata(metadata_path, _metadata_from_headers(metadata, now + config.min_ttl))
            return TileImage(coord=coord, content=path.read_bytes(), source="cache")
        raise TileFetchError(f"tile fetch failed for {coord.z}/{coord.x}/{coord.y}: HTTP {exc.code}") from exc

    if not content:
        raise TileFetchError(f"tile fetch failed for {coord.z}/{coord.x}/{coord.y}: empty response")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _write_metadata(metadata_path, _metadata_from_headers(response_headers, _expiry_from_headers(response_headers, now, config.min_ttl)))
    return TileImage(coord=coord, content=content, source="network")


def _validate_coord(coord: TileCoord, config: TileFetchConfig) -> None:
    if coord.z < config.min_zoom or coord.z > config.max_zoom:
        raise TileFetchError(f"zoom {coord.z} outside allowed range {config.min_zoom}..{config.max_zoom}")
    n = 2**coord.z
    if coord.x < 0 or coord.x >= n or coord.y < 0 or coord.y >= n:
        raise TileFetchError(f"tile coordinate outside zoom {coord.z} bounds")


def _validate_zoom(zoom: int) -> None:
    if zoom < MIN_ZOOM or zoom > MAX_ZOOM:
        raise TileFetchError(f"zoom {zoom} outside allowed range {MIN_ZOOM}..{MAX_ZOOM}")


def _metadata_path(tile_path: Path) -> Path:
    return tile_path.with_suffix(".json")


def _read_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


def _write_metadata(path: Path, metadata: Mapping[str, str]) -> None:
    path.write_text(json.dumps(dict(metadata), sort_keys=True), encoding="utf-8")


def _metadata_from_headers(headers: Mapping[str, str], expires_at: datetime) -> dict[str, str]:
    metadata = {"expires_at": _format_http_date(expires_at)}
    etag = headers.get("etag", "")
    last_modified = headers.get("last-modified", "")
    if etag:
        metadata["etag"] = etag
    if last_modified:
        metadata["last_modified"] = last_modified
    return metadata


def _is_fresh(metadata: Mapping[str, str], now: datetime) -> bool:
    expires_at = _parse_http_date(metadata.get("expires_at", ""))
    return expires_at is not None and expires_at > now


def _expiry_from_headers(headers: Mapping[str, str], now: datetime, fallback_ttl: timedelta) -> datetime:
    minimum = now + fallback_ttl
    max_age = _cache_control_max_age(headers.get("cache-control", ""))
    if max_age is not None:
        return max(now + max_age, minimum)
    expires_at = _parse_http_date(headers.get("expires", ""))
    if expires_at is not None and expires_at > now:
        return max(expires_at, minimum)
    return minimum


def _cache_control_max_age(value: str) -> timedelta | None:
    for part in value.split(","):
        key, _, raw_value = part.strip().partition("=")
        if key.lower() != "max-age":
            continue
        try:
            seconds = int(raw_value)
        except ValueError:
            return None
        if seconds < 0:
            return None
        return timedelta(seconds=seconds)
    return None


def _parse_http_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_http_date(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def _clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
