from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request

from visualization.tiles import (
    DEFAULT_MAX_TILES,
    DEFAULT_USER_AGENT,
    TileCoord,
    TileFetchConfig,
    TileFetchError,
    fetch_tiles,
    lat_lon_to_tile,
    tile_cache_path,
    tile_coords_for_bounds,
    tile_url,
)


class TileTests(unittest.TestCase):
    def test_default_max_tiles_allows_moderate_single_render_zoom(self) -> None:
        self.assertEqual(DEFAULT_MAX_TILES, 64)

    def test_tile_url_uses_osm_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TileFetchConfig(cache_root=Path(tmpdir))

            self.assertEqual(
                tile_url(TileCoord(z=12, x=2376, y=1190), config),
                "https://tile.openstreetmap.org/12/2376/1190.png",
            )

    def test_lat_lon_to_tile_returns_web_mercator_tile_coordinate(self) -> None:
        coord = lat_lon_to_tile(60.1699, 24.9384, 12)

        self.assertEqual(coord, TileCoord(z=12, x=2331, y=1185))

    def test_tile_coords_for_bounds_returns_sorted_area_tiles(self) -> None:
        coords = tile_coords_for_bounds(60.16, 24.93, 60.17, 24.94, 14)

        self.assertEqual(
            coords,
            (
                TileCoord(z=14, x=9326, y=4742),
                TileCoord(z=14, x=9326, y=4743),
                TileCoord(z=14, x=9327, y=4742),
                TileCoord(z=14, x=9327, y=4743),
            ),
        )

    def test_fetch_tiles_writes_cache_with_user_agent_and_metadata(self) -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmpdir:
            opener = FakeOpener(
                FakeResponse(
                    b"png",
                    headers={
                        "cache-control": "max-age=3600",
                        "etag": '"abc"',
                        "last-modified": "Tue, 16 Jun 2026 11:00:00 GMT",
                    },
                )
            )
            config = TileFetchConfig(cache_root=Path(tmpdir))
            coord = TileCoord(z=1, x=1, y=0)

            result = fetch_tiles((coord,), config, opener=opener, now=now)

            self.assertEqual(result.tiles[0].content, b"png")
            self.assertEqual(result.tiles[0].source, "network")
            self.assertEqual(tile_cache_path(coord, config).read_bytes(), b"png")
            self.assertEqual(opener.requests[0].headers["User-agent"], DEFAULT_USER_AGENT)
            self.assertIn('"expires_at"', tile_cache_path(coord, config).with_suffix(".json").read_text(encoding="utf-8"))

    def test_fetch_tiles_applies_minimum_ttl_floor(self) -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmpdir:
            opener = FakeOpener(FakeResponse(b"png", headers={"cache-control": "max-age=60"}))
            config = TileFetchConfig(cache_root=Path(tmpdir))
            coord = TileCoord(z=1, x=1, y=0)

            fetch_tiles((coord,), config, opener=opener, now=now)

            metadata = tile_cache_path(coord, config).with_suffix(".json").read_text(encoding="utf-8")
            self.assertIn("Tue, 23 Jun 2026 12:00:00 GMT", metadata)

    def test_fetch_tiles_reads_fresh_cache_without_network(self) -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TileFetchConfig(cache_root=Path(tmpdir))
            coord = TileCoord(z=1, x=1, y=0)
            path = tile_cache_path(coord, config)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"cached")
            path.with_suffix(".json").write_text('{"expires_at": "Tue, 16 Jun 2026 13:00:00 GMT"}', encoding="utf-8")
            opener = FakeOpener(FakeResponse(b"network", headers={}))

            result = fetch_tiles((coord,), config, opener=opener, now=now)

            self.assertEqual(result.tiles[0].content, b"cached")
            self.assertEqual(result.tiles[0].source, "cache")
            self.assertEqual(opener.requests, [])

    def test_fetch_tiles_uses_conditional_headers_for_expired_cache(self) -> None:
        now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TileFetchConfig(cache_root=Path(tmpdir))
            coord = TileCoord(z=1, x=1, y=0)
            path = tile_cache_path(coord, config)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"old")
            path.with_suffix(".json").write_text(
                (
                    '{"expires_at": "Tue, 16 Jun 2026 11:00:00 GMT", '
                    '"etag": "\\"abc\\"", '
                    '"last_modified": "Tue, 16 Jun 2026 10:00:00 GMT"}'
                ),
                encoding="utf-8",
            )
            opener = FakeOpener(FakeResponse(b"new", headers={}))

            result = fetch_tiles((coord,), config, opener=opener, now=now)

            self.assertEqual(result.tiles[0].content, b"new")
            self.assertEqual(opener.requests[0].headers["If-none-match"], '"abc"')
            self.assertEqual(opener.requests[0].headers["If-modified-since"], "Tue, 16 Jun 2026 10:00:00 GMT")

    def test_fetch_tiles_rejects_over_limit_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TileFetchConfig(cache_root=Path(tmpdir), max_tiles=1)

            with self.assertRaises(TileFetchError):
                fetch_tiles((TileCoord(z=2, x=1, y=1), TileCoord(z=2, x=1, y=2)), config, opener=FakeOpener())

    def test_invalid_zoom_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = TileFetchConfig(cache_root=Path(tmpdir))

            with self.assertRaises(TileFetchError):
                tile_url(TileCoord(z=30, x=0, y=0), config)


class FakeResponse:
    def __init__(self, content: bytes, headers: dict[str, str]) -> None:
        self._content = content
        self.headers = headers

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self._content


class FakeOpener:
    def __init__(self, response: FakeResponse | None = None) -> None:
        self.response = response or FakeResponse(b"", headers={})
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        return self.response
