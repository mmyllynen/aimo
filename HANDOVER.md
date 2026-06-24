# Aimo Handover

This is the fast entrypoint for a new session. Read `LOCAL.md` first when present; it contains local-only FUSE/sshfs, restart, and runtime notes and is intentionally ignored by git.

## State

- Aimo is production-capable as a Discord bot with SQLite storage, typed workflow dispatch, GPX ingest, workout management/chat, visualization, debug traces, and fake-boundary tests.
- Implemented user-facing surfaces include `/aimo`, `/gpx`, `/help`, `/treenit`, `/asetukset`, `/debug`, mention chat, GPX ingest, workout route/period charts, social images, and a formal `overlay=...` animation path.
- `/aimo` is the chat/natural-language slash surface. `/gpx tallenna` handles GPX slash upload with optional `nimi`.
- `/treenit` supports list/show/current/set-current/delete with same-user button confirmation, rename, and tag add/remove. `/asetukset` shows settings and sets HR zones.
- `/help` has deterministic topics for general help, commands, visualization, social images, and privacy/storage/model-context behavior.
- Visualizations use Pillow-based renderers for route maps, period charts, social-image rendering, and overlay-animation rendering. Overlay video formats use `ffmpeg` or `imageio-ffmpeg`.
- Route maps use MapTiler raster tiles when configured, with local OSM fallback. Aimo owns route overlays, unified markers, waypoint/reittimerkki legends, kilometer markers, route coloring, and the single-route elevation overlay.
- Single-route maps show GPX waypoints by default, support `-waypoints` / `-reittimerkit`, and show a bottom elevation overlay with grade coloring, waypoint/start/finish/min/max labels, a kilometer axis, and `+overlay:elevation` / `-overlay:elevation` visibility controls. On route maps, `+elevation` / `+korkeus` colors the route by absolute elevation, while `+grade` / `+jyrkkyys` / `+kaltevuus` colors the route with the same grade palette as this elevation overlay. `+direction` / `+suunta` adds sparse direction chevrons to the route.
- Social images use `output_mode=social_image`, plustägit such as `+social` / `+somekuva` / `+poster`, and bounded tarkenteet such as `dim=45` on inline or `style:` / `tyyli:` lines.
- Overlay animations are a deterministic bundle MVP triggered with `overlay=map`, `overlay=route`, `overlay=hr`, or combinations such as `overlay=route,map,hr`. Example: `@aimo overlay=route,map,hr dist=12.4km duration=60s size=1280x720 tail=200m`. Output is one file per requested overlay type; transparent MOV is the default, `fps=10`, `transparent=true`, and `map_layout=circle` are defaults.
- Overlay map is a north-up circular MapTiler/OSM-tile widget with a centered marker, route/tail overlays, compass tape, local camera, tile cache, `streets-v2-dark` default style, `map_style=outdoor-dark` support, and light tile alpha. Route overview overlay is a separate no-tile transparent layer that fits the full workout route into a small panel with completed route, optional tail, and current marker. Dense overview polylines are thinned for drawing performance. HR overlay is a separate transparent drawing line chart with the current bpm value.
- Overlay `auto_zoom=true` is default: slow GPX sections tighten map `radius` toward `radius_min=100m` using `auto_zoom_fast=4:00/km`, `auto_zoom_slow=9:00/km`, and `auto_zoom_sample=20s`. Default tail is time-based (`tail_time=30s`, bounded by `tail_min=60m` and `tail_max=250m`) so tail length indicates speed. Explicit `tail=...` switches to fixed-distance tail mode. Autozoom never changes video timing or GPX elapsed-time sync.
- Overlay bundle replies are one concise summary message with one row per overlay, for example `Reitti: <url>`, `Kartta: <url>`, and `Syke: <url>`. Public artifact filenames are descriptive and editor-friendly, e.g. `lohja-running_2026-06-24_12.40-12.90km_map.mov`; repeated renders of the same public artifact path overwrite the previous file.

## Current Focus

Use `TODO.md` for the backlog. Route visualization and the route/map/HR overlay bundle are usable. Current high-value directions are overlay browser-preview/MP4 companion files, HR-zone styling, richer route-overview styling, lower-third/compact HR layouts, workout import/export, search/filter, notes/metadata, richer non-route chart requests, retention/backup/health tooling, and bounded context improvements.

## Useful Checks

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

Production-oriented:

```bash
python3 aimo.py --preflight --config aimo.conf
python3 scripts/production_smoke.py --config aimo.conf --log logs/bot.log
```

## Discord Smoke Ideas

```text
@aimo piirrä viimeisimmän treenin reitti kartalle
@aimo piirrä viimeisin treeni kartalle +hr
@aimo piirrä kuluvan kuun treenien reitit kartalle
@aimo piirrä kuluvan kuun treenien sykealueet piirakkana
@aimo piirrä somekuva viimeisestä treenistä +poster +distance +hr
@aimo piirrä somekuva viimeisestä treenistä +routeonly
@aimo overlay=map,hr dist=0.4km duration=5s size=1280x720 format=gif
@aimo overlay=map,hr dist=12.4km duration=60s size=1280x720 tail=200m
@aimo overlay=route,map,hr dist=12.4km duration=60s size=1280x720 route_position=left
```

After a MapTiler route smoke test, expected artifact metadata includes `map_background=maptiler_tiles`, `tile_provider=maptiler`, `tile_status=ok`, `tile_size=512`, and `route_overlay=aimo`. If it falls back to OSM, inspect `tile_error` and remote map config without printing secrets.
After an overlay smoke test, expected bundle behavior is one summary message plus either Discord file attachments or public URLs. Expected filenames include workout slug, date, distance range, and overlay type.
