# Aimo Handover

This is the fast entrypoint for a new session. This repository is the source of truth for code and tracked templates.

For environment-specific details that must not go to version control, read `config.local.notes.md` first. It records the FUSE/sshfs workspace setup, remote restart command, and local operating reminders.

## Runtime

- Production host: `mushroom` via `~/.ssh/config`.
- Production directory: the same checkout is mounted remotely; local edits in `/home/myllymik/Projects/aimo` are visible to the remote bot workspace.
- Runtime command: `python3 aimo.py --config aimo.conf --run-discord`
- Restart command:

```bash
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && AIMO_BOT_DIR=/home/myllymik/chatgpt ./check-restart.sh --force"
```

- The `AIMO_BOT_DIR=/home/myllymik/chatgpt` override matters; the script default points elsewhere.
- Local config and runtime data are intentionally untracked.
- Do not use `scp`, remote patch transfer, or ad hoc remote edits for normal updates from this workspace.

Useful local deployment checks:

```bash
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "pgrep -af 'python3.*aimo.py.*--run-discord'"
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "tail -n 40 ~/chatgpt/logs/bot.log"
```

## Current State

- Discord runtime, workout storage, GPX ingest, workout chat, period selection, workout-set visualizations, and route plotting are implemented.
- User/workout data is guild-scoped as intended.
- Visualization rendering currently uses the renderer abstraction:
  - Configurable per chart type through `RenderersConfig` / `aimo.conf`.
  - `internal` renderer remains available.
  - `pillow` renderer is the current default path for all chart types in the active config.
  - `visualization/pillow_renderer.py` is an active source file; in the current worktree it may still be untracked, so check it explicitly.
- Route maps currently use:
  - MapTiler raster tiles as primary base map provider when `[maps] provider = maptiler` and `maptiler_api_key` / `MAPTILER_API_KEY` is set.
  - Local OSM tile renderer as fallback.
  - Pillow-rendered Aimo-owned route overlay, start/end markers, title, route/data legend, and optional route coloring. The provider no longer draws the route.
  - Tile cache paths:
    - MapTiler: `data/cache/maptiler_tiles/<map_id>/<z>/<x>/<y>.png`
    - OSM fallback: `data/cache/osm_tiles/<z>/<x>/<y>.png`
- Static Maps API was removed from the active implementation because MapTiler Static Maps returned HTTP 403 on the free plan. MapTiler raster tiles were verified to work with the configured key.
- Visualizations now render at HD default size, with plus-tag aspect overrides:
  - default: 1920x1080
  - `+square`: 1080x1080
  - `+portrait`: portrait HD aspect
- Plus tags are active deterministic visualization overrides:
  - Data tags include `+hr`, `+elevation`, and `+pace`.
  - Route maps support one data tag at a time. If multiple are supplied, the first supported data tag is used and the user gets a deterministic notice.
  - Aspect tags are separate from data tags, so route requests can combine e.g. `+hr +square`.
  - Hashtag support was intentionally replaced with plus tags because Discord matches `#...` against channel names.
- Route coloring:
  - `+hr`, `+elevation`, and `+pace` color the route by the selected metric.
  - When a route data metric is active, the normal per-route legend color is not overlaid; the scale legend is shown instead.
  - Pace is preprocessed through metric metadata before rendering, with robust outlier handling and descending direction semantics so faster pace maps as better.
  - Route data coloring is drawn as connected line segments, not separate point dots.
- Visual overlay style:
  - Route and non-route charts use consistent dark translucent overlays with white text.
  - Non-route charts have a dark aligned frame and a blue/mint gradient background.
  - Current gradient uses the `cool blue mint plus` palette diluted 30% toward neutral light background in `visualization/pillow_renderer.py`.
  - Non-route title/legend overlays are aligned to the frame; route overlays keep top-left and top-right relative placement.
- Text/localization state:
  - Single-workout charts use the workout title directly, e.g. `Sipoo Running`.
  - Period/workout-set charts use localized chart subjects, e.g. `Sykealueet`, `Mittarit`, `Vauhti`.
  - Non-route subtitles use the route-style localized summary: `d/m/yyyy h:mm - 5.4 km - 33min 36s - Keskisyke 124`, or for periods `1/6/2026 - 17/6/2026 - ...`.
  - Non-route labels such as legend and common axis labels are localized, e.g. `Legend -> Selite`, `Share -> Osuus`.
- Discord UX:
  - Typing indicator and a `työstän...` placeholder are used for visualization work, and the placeholder is replaced by the final image.
  - Typing indicator is mention-gated; normal channel chatter should not trigger it.
- Last targeted verification before this handoff:
  - `python3 -m py_compile visualization/service.py visualization/render.py visualization/pillow_renderer.py tests/test_visualization_specs.py`
  - `python3 -m unittest tests.test_visualization_specs`
  - `python3 -m unittest tests.test_visualization_workflow`
  - `python3 -m unittest tests.test_visualization_specs.VisualizationSpecTests.test_pillow_renderer_renders_all_chart_types_as_png`
  - `git diff --check -- visualization/service.py visualization/render.py visualization/pillow_renderer.py tests/test_visualization_specs.py`
- Remote bot was restarted after the latest gradient dilution and reported `Restart complete`.

## Next Smoke Tests

In Discord:

```text
@aimo piirrä viimeisimmän treenin reitti kartalle
@aimo piirrä viimeisin treeni kartalle +hr
@aimo piirrä kuluvan kuun treenien reitit kartalle
@aimo piirrä kuluvan kuun treenien sykealueet piirakkana
@aimo piirrä kuluvan kuun treenien sykealueet pylväinä +square
```

After a route smoke test with MapTiler enabled, inspect artifact metadata. Expected for MapTiler:

- `map_background = maptiler_tiles`
- `tile_provider = maptiler`
- `tile_status = ok`
- `tile_size = 512`
- `route_overlay = aimo`

If it says `map_background = osm`, inspect `tile_error` and confirm remote config has `provider=maptiler` and a set key without printing the key.

Useful local no-Discord render check:

```bash
python3 -m unittest tests.test_visualization_specs.VisualizationSpecTests.test_pillow_renderer_renders_all_chart_types_as_png
```

The latest local preview images from the previous session were written to:

- `artifacts/local-text-preview-period-zones.png`
- `artifacts/local-text-preview-single-hr.png`

## Development Focus

Read `TODO.md` first. Current priorities are user-visible workout features, production smoke/health tooling, retention/backup operations, and better bounded context.

## Guardrails

- Do not use `legacy/` as implementation guidance unless explicitly asked.
- Do not commit `aimo.conf`, tokens, SQLite databases, GPX files, logs, or artifacts.
- Direct messages are rejected by runtime policy.
- Normal guild messages may be stored as history but should not trigger replies.
- First active user interaction is tracked separately from passive history observation.
- Keep raw GPX and workout point rows out of model planning inputs.
- Do not implement natural-language intent interpretation in Python. The LLM returns formal intent; Python owns deterministic state, validation, storage, rendering, and execution.
- Keep Discord-specific objects at adapter boundaries.
- Deterministic bot-owned messages must use i18n keys, not hard-coded user-facing text.

## Verification

Default handoff checks:

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

## Idea Backlog

These are not committed requirements, but useful directions to revisit.

### Visualization Plus Tags

Dataset and aspect plus tags are implemented. Potential future additions:

- `+xaxisdistance`: force `x_metric = distance_km`
- `+xaxistime`: force `x_metric = elapsed_s`
- `+ascent`: force or add ascent metrics
- `+bar`, `+line`, `+pie`, `+map`: force chart kind
- `+smallmultiples`, `+singleaxis`: force layout mode
- `+currentmonth`, `+lastweek`, `+allworkouts`: explicit period selectors

Guardrail remains: plus tags are a small formal override vocabulary, not natural-language intent parsing in Python. Unknown plus tags can be ignored or reported as unsupported through a deterministic validation path.

### Social Image Mode

Add a more explicitly shareable workout image mode if the normal chart layouts are not enough:

- `+social`, `+somekuva`: enable social layout

Potential design:

- Full-bleed route map as the background.
- Aimo renders the route overlay itself, so later route coloring by HR zone/pace/elevation still works.
- Overlay panel with key stats: distance, duration, pace, ascent, avg HR, date, workout title.
- Optional compact zone summary or elevation sparkline.
- Keep provider base-map cache reusable by separating base map from overlay content.

Implementation note: this should likely be a `layout_mode` or `output_mode` in the formal visualization intent, with plus tags acting only as explicit overrides.
