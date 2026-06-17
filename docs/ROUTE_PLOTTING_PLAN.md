# Route Plotting Plan

## Goal

Support route plotting on a map background for workout visualizations.

Example requests:

```text
@aimo piirrä viimeisimmän treenin reitti kartalle
@aimo näytä kuluvan kuun lenkkien reitit kartalla
@aimo plottaa aktiivisen treenin reitti
```

The LLM interprets the natural-language request into a formal visualization intent. Python resolves workout scope, reads owned workout points, fetches and caches map tiles, projects GPS coordinates, and renders the PNG.

The preferred long-term map background provider is MapTiler raster tiles when configured, with the local OSM tile renderer retained as a fallback. Aimo owns all route overlays.

## Principles

- [ ] LLM decides whether the requested visualization is a route map.
- [ ] Python owns workout ownership, point access, route bounds, tile fetching, caching, map projection, rendering, attribution, and errors.
- [ ] Do not infer route/map intent from user text in Python.
- [ ] The same route plotting path should support single workouts, comparisons, and period workout sets.
- [ ] Raw point rows and raw GPX must not be sent to model planning inputs.

## OSM Tile Policy Requirements

If using `tile.openstreetmap.org`:

- [x] Use `https://tile.openstreetmap.org/{z}/{x}/{y}.png`.
- [x] Show visible attribution: `© OpenStreetMap contributors`.
- [x] Send a stable identifying HTTP `User-Agent`.
- [x] Cache tiles locally according to HTTP caching headers, or at least 7 days.
- [x] Do not bulk download, prefetch large areas, or build offline tile archives.
- [x] Keep usage modest; OSMF tile service has no SLA.

Reference: https://operations.osmfoundation.org/policies/tiles/

## Formal Intent Shape

Route plotting should use the existing visualization workflow with additional canonical primitives:

```json
{
  "chart_kind": "map",
  "x_metric": "longitude",
  "requested_metrics": ["route"],
  "workout_selector": {
    "type": "latest | active | id | current_month | date_range | all_workouts",
    "value": "",
    "count": null,
    "limit": null
  },
  "date_range": {
    "start": "",
    "end": ""
  },
  "layout_mode": "auto",
  "transform_hints": []
}
```

`route` is a canonical visualization metric meaning that the renderer needs latitude/longitude route points. Python must validate that usable GPS points exist.

## Dataset Model

Add a dataset:

```text
route_points
```

Columns:

- `workout_id`
- `workout_title`
- `point_index`
- `latitude`
- `longitude`
- `elapsed_s`
- `distance_km`
- `elevation_m`
- `heart_rate_bpm`
- `segment_index`

The LLM-visible manifest may include column metadata and row counts, but not raw rows.

## Rendering Model

Python should:

- [x] Collect route points for the resolved scope.
- [x] Compute route bounding box.
- [x] Add visual padding.
- [x] Select a Web Mercator zoom level.
- [x] Fetch only the tiles required for the current render.
- [x] Stitch tiles into the background.
- [x] Project lat/lon points to image pixels.
- [x] Draw one or more route polylines.
- [x] Draw start/end markers.
- [x] Draw legend and OSM attribution.
- [x] Use a map-first viewport where the map fills the image and title/legend render as overlays.
- [x] Select tile zoom from the final viewport so raster source pixels are at least 1:1 with output pixels.
- [x] Fetch provider base map tiles without route/path overlays.
- [x] Draw route overlays in Aimo so later segment coloring can use heart-rate zones, pace, elevation, or splits.

## Tile Cache

Add `visualization/tiles.py` for:

- [x] Tile URL construction.
- [x] Stable app-specific `User-Agent`.
- [x] Local cache path, for example `data/cache/osm_tiles/{z}/{x}/{y}.png`.
- [x] HTTP caching header support.
- [x] Minimum 7-day TTL fallback.
- [x] Conditional requests when expired.
- [x] Max tile count per render, currently 64 tiles.
- [x] Fetch timeout.

If tile background fetch fails, prefer rendering the route on a plain light background with a warning metadata field over failing the entire request.

## Phases

### Phase 1: Intent Foundation

- [x] Document route plotting plan.
- [x] Add canonical visualization metric `route`.
- [x] Add `map` as a formal visualization chart kind in LLM contracts.
- [x] Update OpenAI schema tests so `route` and `map` are present.
- [ ] Route map rendering is not implemented in this phase.
- [ ] Tile fetching is not implemented in this phase.

### Phase 2: Route Dataset And Validation

- [x] Add `route_points` dataset.
- [x] Add route point availability validation.
- [x] Add user-facing missing-route-data error.
- [x] Add tests proving raw points are not sent to LLM input.

### Phase 3: Projection And Plain Route Renderer

- [x] Add Web Mercator projection helpers.
- [x] Render route polyline on a plain background.
- [x] Draw start/end markers.
- [x] Support single workout and workout set scopes.

### Phase 4: OSM Tile Fetching And Cache

- [x] Add tile fetcher.
- [x] Add local tile cache.
- [x] Add identifying `User-Agent`.
- [x] Add tile count and zoom limits.
- [x] Expose attribution text for renderer integration.
- [x] Add tests with fake HTTP tile responses.

### Phase 5: Map Renderer Integration

- [x] Integrate OSM tile background into `render_route_map_png`.
- [x] Draw visible OSM attribution.
- [x] Store map metadata in rendered artifacts.
- [x] Add Discord smoke-test cases.
- [x] Keep Discord-friendly output dimensions while using viewport-based native-pixel tile zoom.
- [x] Keep route geometry out from under title and legend overlay safe areas.
- [x] Add MapTiler raster tile provider for high-quality cached base map tiles.
- [x] Cache provider tiles by provider, map style, z, x, and y.
- [x] Keep API keys out of tile cache paths and artifact metadata.
- [x] Draw route, start marker, end marker, title, and legend in Aimo over cached base map tiles.
- [x] Keep local OSM tile renderer as fallback when the static provider is unavailable or unconfigured.

Configuration:

```ini
[maps]
provider = maptiler
maptiler_api_key =
maptiler_map_id = streets-v4
timeout_s = 10
```

Prefer setting the API key through `MAPTILER_API_KEY` or a local untracked config file.

Smoke tests:

- [ ] `@aimo piirrä viimeisimmän treenin reitti kartalle`
- [ ] `@aimo piirrä kuluvan kuun treenien reitit kartalle`
- [ ] Repeat the latest-workout route request and confirm it still works when tiles are served from cache.

### Phase 6: Future Enhancements

- [ ] Multiple route opacity and color handling.
- [ ] Heart-rate-colored route.
- [ ] Elevation-colored route.
- [ ] Split/lap markers.
- [ ] Distance markers.
- [ ] Provider override for commercial or self-hosted OSM-derived tiles.
- [ ] Optional vector tile support.
