# Aimo Handover

This is the fast entrypoint for a new session. Read `LOCAL.md` first when present; it contains local-only FUSE/sshfs, restart, and runtime notes and is intentionally ignored by git.

## State

- Aimo is production-capable as a Discord bot with SQLite storage, typed workflow dispatch, GPX ingest, workout management/chat, visualization, debug traces, and fake-boundary tests.
- Implemented user-facing surfaces include `/aimo`, `/gpx`, `/help`, `/treenit`, `/asetukset`, `/debug`, mention chat, GPX ingest, workout route/period charts, and social images.
- `/aimo` is the chat/natural-language slash surface. `/gpx tallenna` handles GPX slash upload with optional `nimi`.
- `/treenit` supports list/show/current/set-current/delete with same-user button confirmation, rename, and tag add/remove. `/asetukset` shows settings and sets HR zones.
- `/help` has deterministic topics for general help, commands, visualization, social images, and privacy/storage/model-context behavior.
- Visualizations use `internal` or `pillow` renderers through config. `pillow` is the current default path and includes route maps, period charts, and social-image rendering.
- Route maps use MapTiler raster tiles when configured, with local OSM fallback. Aimo owns route overlays, unified markers, waypoint/reittimerkki legends, kilometer markers, route coloring, and the single-route elevation overlay.
- Single-route maps show GPX waypoints by default, support `-waypoints` / `-reittimerkit`, and show a bottom elevation overlay with grade coloring, waypoint/start/finish/min/max labels, a kilometer axis, and `-elevation` / `-korkeus` hiding.
- Social images use `output_mode=social_image`, plustägit such as `+social` / `+somekuva` / `+poster`, and bounded tarkenteet such as `dim=45` on inline or `style:` / `tyyli:` lines.

## Current Focus

Use `TODO.md` for the backlog. Route visualization is considered sufficiently complete for now. Current high-value directions are workout import/export, search/filter, notes/metadata, richer non-route chart requests, multi-file GPX ingest, retention/backup/health tooling, and bounded context improvements.

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
```

After a MapTiler route smoke test, expected artifact metadata includes `map_background=maptiler_tiles`, `tile_provider=maptiler`, `tile_status=ok`, `tile_size=512`, and `route_overlay=aimo`. If it falls back to OSM, inspect `tile_error` and remote map config without printing secrets.
