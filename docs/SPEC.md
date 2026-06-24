# Aimo Specification

This is the durable product and application contract for Aimo. Keep implementation notes, temporary plans, and local machine details out of this file.

## Product

Aimo is a multilingual Discord bot for concise channel chat, workout coaching, GPX ingest, workout management, heart-rate zone configuration, natural-language workout visualizations, and bounded debug traces.

The bot may use LLMs for language interpretation and prose, but deterministic application code owns state transitions, validation, storage, rendering, permissions, and error handling.

Supported deterministic UI languages are Finnish (`fi`) and English (`en`). The active language comes from `aimo.conf`; Finnish is the default. Bot-owned deterministic messages use translation keys, and catalog keys/placeholders must stay in parity across supported languages.

## Runtime Policy

- Direct messages are rejected.
- Guild and optional channel allowlists are enforced before dispatch.
- The bot responds only to mentions and slash commands.
- Normal guild messages may be stored as bounded history and remain no-op responses.
- First active user interaction is tracked separately from passive observation.
- Admin users receive a DM on the first accepted active interaction from a user.
- Discord-specific objects stay in the adapter boundary; workflows operate on canonical events and workflow results.
- Broad mentions are disabled in outgoing messages.

## Privacy And Ownership

- Workout data belongs to the Discord user who uploaded it.
- Users cannot access another user's workouts unless explicit sharing is added later.
- Channel history, rendered artifacts, and debug traces are operational data and must be bounded/redacted according to policy.
- Raw GPX and full workout point arrays stay in deterministic storage/services and are not sent to routing or model planning inputs.
- Model inputs contain only bounded context and compact workout facts or manifests needed for the request.

## Surfaces

Aimo supports:

- public `@Aimo` mentions in allowed guild channels
- GPX attachments on supported mention/slash inputs
- `/aimo`
- `/help`
- `/treenit`
- `/debug`

Slash commands should be registered for configured allowed guilds when a guild allowlist exists.

## Workflows

### Chat

General mention-based chat produces a concise public reply in the configured language. Replies should avoid internal routing, JSON, prompts, model details, traces, and unavailable-data claims.

### Help

`/help` and help-like mentions are deterministic and do not use the LLM.

Supported topics:

- `yleinen` / general help
- `komennot` / command summary
- `visualisointi` / chart and plus-tag help
- `somekuva` / social-image style help
- `privacy` / storage, model context, deletion/export status, retention expectations

Slash help replies are ephemeral where Discord supports it. Mention-triggered help may be public.

### GPX Ingest

Supported attachments are `.gpx` and common GPX/XML content types. Ingest validates size, type, XML shape, and useful track/route/waypoint content. Valid GPX is stored as a user-owned workout; duplicate detection uses owner plus raw-content SHA-256. Ingest sets the imported workout as current.

For single-GPX mention uploads, the workout title may be overridden with a deterministic tarkenne (`nimi="..."` or `name="..."`) or, if no tarkenne is present, an LLM-extracted explicit naming request such as `anna sille nimeksi "Aamulenkki"`. Multiple-GPX uploads ignore shared naming requests and keep per-file/GPX-derived names.

Slash upload uses `/gpx tallenna liite nimi`. `liite` is required; `nimi` is optional and applies only to that single uploaded GPX.

Invalid or unsupported attachments return stable localized errors. Multiple GPX attachments are ingested independently; shared naming overrides are intentionally ignored for multi-attachment uploads.

### Workout Management

`/treenit` is deterministic and avoids LLM dependency.

Subcommands:

- `listaa`
- `nayta` with optional `viite`
- `aktiivinen`
- `aseta_aktiivinen` with optional `viite`
- `poista` with optional `viite`
- `nimea` with optional `viite` and required `nimi`
- `tagaa` with optional `viite` and required `tagi`
- `poista_tagi` with optional `viite` and required `tagi`

Rules:

- Workout references are owner-scoped and may use id, active/latest selector, recent list index, date, date range, tag, kind/type, or title fragment.
- `nayta`, `nimea`, `tagaa`, and `poista_tagi` set the resolved workout as current.
- `poista` creates a same-user 60-second button confirmation before deleting.
- Workout management replies should usually be ephemeral unless a public mode is intentionally added.

### Settings

`/asetukset` is deterministic and user-owned.

Subcommands:

- `nayta`
- `sykerajat` with required `zones`

Rules:

- `nayta` returns the user's current settings, including HR zones.
- `sykerajat` accepts one max-HR value or five increasing BPM upper limits.
- Settings replies should usually be ephemeral unless a public mode is intentionally added.

### Workout Chat

Workout chat answers training/workout questions from resolved user-owned workout facts. It must not invent HR, pace, duration, elevation, splits, route details, or recovery claims. Missing data should be stated plainly.

The formal plustägit `+estimate`, `+ennuste`, and `+aikaennuste` request a deterministic route time estimate for the resolved workout or route. Natural-language route time questions are interpreted through a typed route-time-estimate intent. Python owns workout resolution, data access, route metrics, history comparison, and the estimate calculation. Formal-tag replies may be deterministic; natural-language replies may be conversational LLM prose grounded only in Python-calculated estimate facts. The reply must include an estimate, likely range or uncertainty, confidence, and data limitations. LLMs must not invent the estimate.

Route-time estimation should move toward precomputed compact workout features. GPX ingest is the preferred point to calculate estimate-useful fields such as ascent/descent, grade distribution, sustained climb/descent summaries, route shape signatures, distance/elevation coverage, route centroid/bounds, and data-quality flags. These derived features should be stored owner-scoped in SQLite with a version marker and indexed comparison keys so estimation can select comparable workouts without scanning full point streams or recomputing the entire workout set on demand. Existing workouts need an explicit deterministic backfill path when the feature schema is introduced or upgraded.

When feature records are available, route-time estimation weights comparable workouts by route similarity rather than using all activities equally. Similarity factors include activity kind, distance, ascent per kilometer, grade profile, distance/ascent bands, recency when applicable, and route signature matches. The model metadata may be exposed in debug or grounded LLM facts, but raw point streams remain outside model inputs.

Users may ask Aimo to explain the previous route-time estimate conversationally. This explanation uses the latest stored route-time-estimate metadata from the channel, including model name, baseline pace, ascent and distance adjustments, uncertainty source, comparison counts, effective sample size, and compact similarity scores. The explanation path must not recalculate from raw points or expose raw GPX/point streams to the LLM.

If a natural-language route-time request includes an intended date, the typed LLM intent may return `target_date` and `activity_intent`. Python validates the date, resolves route location from compact feature metadata or route points, retrieves a configured weather forecast for that date/location, and applies a deterministic weather adjustment to the base route-time estimate. If no forecast is available, the provider is disabled, or the date is outside the forecast window, Python falls back to deterministic seasonal climatology and records that limitation. Weather-aware conversational replies are grounded only in compact Python-calculated weather facts, base estimate, adjusted estimate, adjustment components, source, and limitations. The LLM must not infer or invent weather.

Route-time model quality should be measured with deterministic owner-scoped backtesting. Completed activities can be validated with leave-one-out estimates that compare predicted duration against actual stored duration, track signed and absolute error, and measure whether predicted ranges cover actual outcomes. These calibration reports should guide similarity weights, confidence thresholds, and uncertainty ranges before adding more complex model behavior.

Current-workout context is internal workflow state. It is updated by GPX ingest, deterministic workout commands, or explicit structured LLM `context_update` fields after safe single-workout resolution.

### Visualization

Aimo turns natural-language workout visualization requests into PNG artifacts. It also supports a first deterministic overlay-animation MVP for short workout clips.

Pipeline:

```text
natural language
-> visualization intent
-> dataset request/resolution
-> compact dataset manifest
-> visualization spec
-> validator/compiler
-> renderer
-> PNG artifact
```

The pipeline stays generic. Add reusable datasets, metric metadata, transforms, marks, encodings, validators, or renderer primitives instead of metric-specific Python branches.

Supported selectors include latest, active, explicit id, list index, date/date range, tag, kind/type, recent N, and period selectors such as current/last week/month, rolling days, all workouts, and calendar year to date.

Canonical metrics include:

- `timestamp_utc`
- `elapsed_s`
- `distance_km`
- `heart_rate_bpm`
- `pace_s_per_km`
- `elevation_m`
- `cadence_spm`
- `duration_s`
- `ascent_m`
- `avg_hr_bpm`
- `max_hr_bpm`
- `time_in_zone_s`
- `zone_share`
- `route`

Supported chart kinds are `auto`, `line`, `bar`, `pie`, and `map`. Supported output modes are `chart` and `social_image`.

Overlay animation is currently a formal-control MVP, not a general natural-language workflow. The formal tarkenne `overlay=map`, `overlay=route`, `overlay=hr`, or combinations such as `overlay=route,map,hr` requests one or more animated workout overlays from one owner-scoped workout. Python owns workout resolution, point access, validation, frame rendering, artifact storage, and errors.

Supported MVP overlay controls:

- `overlay=map,hr` selects overlay outputs. `map` renders the circular local map overlay, `route` renders a separate full-route overview overlay without tiles, and `hr` renders a separate heart-rate curve overlay. Multiple values produce multiple files from the same request.
- `start=12.4km` selects the route distance where the rendered segment starts.
- `dist=12.4km` selects the GPX route distance shown at the start of a real-time map overlay clip.
- `distance=12.4km` is an alias for `start`.
- `window=500m` or `window=0.5km` selects the source route distance window.
- `length=5s` selects output animation duration.
- `duration=60s` selects output duration, especially for real-time clips.
- `fps=10` selects output frame rate within bounded limits.
- `size=1280x720` selects output dimensions within bounded limits.
- `format=gif` selects animated GIF preview output.
- `format=webm` selects WebM/VP9 output and requires system `ffmpeg` or the `imageio-ffmpeg` package.
- `format=mov` selects QuickTime/ProRes 4444 output with alpha support for video editors such as DaVinci Resolve.
- `format=mp4` selects H.264 MP4 output for smaller opaque clips; MP4 output does not preserve alpha transparency.
- If `format` is omitted, transparent overlays default to `mov`, and opaque overlays default to `mp4`.
- `transparent=true` or `background=transparent` renders transparent RGBA frames for alpha-capable outputs. The default is `transparent=true`.
- `map_layout=circle` renders a framed circular map widget. It is the default and defaults to `map=tiles` and `compass=true`.
- `hr_layout=line` renders a heart-rate line that draws in as the GPX distance advances, showing the same trailing route window as the map tail plus the current bpm value.
- `tail_time=30s` makes the default route tail time-based, so the visible tail length acts as a speed indicator.
- `tail_min=60m` and `tail_max=250m` bound the time-based route tail length. When `tail=200m` is explicitly supplied, the tail uses fixed-distance mode instead.
- `auto_zoom=true` dynamically tightens the map radius on slow segments while preserving real-time video sync. In fixed-distance tail mode, it may also tighten the map/HR tail toward `tail_min`.
- `radius_min=100m` sets the closest map radius when auto zoom reaches its slowest-speed limit.
- `auto_zoom_fast=4:00/km` and `auto_zoom_slow=9:00/km` define the pace range used for dynamic zoom. Faster than the fast pace uses the normal `radius`; slower than the slow pace uses `radius_min`.
- `auto_zoom_sample=20s` sets the local elapsed-time window used to estimate pace for zooming.
- `map=schematic` uses the offline schematic route background.
- `map=tiles` uses the configured tile provider with OSM fallback inside the map widget. It is the default for `map_layout=circle`.
- `compass=true` renders a graphical heading compass below the circular map. It is the default for `map_layout=circle`.
- `map_style=dark` selects the MapTiler overlay tile style. The default is `streets-v2-dark`; aliases include `dark`, `outdoor-dark`, `outdoor`, `light`, `dataviz`, `streets`, and `basic-dark`.
- `tile_alpha=0.9` sets raster tile opacity only. Route, tail, current marker, frame, and compass remain opaque.
- `route_position=right` sets the full-route overview panel position for `overlay=route`; supported values are `right`, `left`, and `center`.
- `route_size=360` sets the full-route overview panel size in pixels within bounded limits.
- `route_background=dim` draws a subtle translucent background behind the full-route overview; `route_background=none` draws only the route and marker.
- `route_tail=true` enables the same time/distance tail indicator on the full-route overview.
- `sync=real` advances frame time by GPX elapsed time instead of fitting the selected distance window to the output duration.
- `view=local` uses a moving local route viewport around the current GPX position.
- `radius=300m`, `tail=200m`, and `lookahead=100m` tune the local map camera, recently completed route tail, and upcoming-route bias.
- `workout=...` or `treeni=...` selects active/latest or an exact workout id; otherwise active workout is preferred, then latest.

When `dist` is supplied, the map overlay defaults to `sync=real` and `view=local`: Python interpolates the GPX elapsed time at the requested distance and renders the marker at the same elapsed-time pace as the recorded workout. The local map viewport follows the current route position so movement remains visible on long routes.

Auto zoom never changes frame timing or GPX elapsed-time synchronization. It changes only the rendered map scale and HR distance window so slow route sections remain visibly moving.

The circular tile-map overlay is north-up: map tiles do not rotate. Aimo renders the tile background inside a circular alpha mask, draws the route, recently completed tail, and position marker opaquely on top, then renders a compass tape below the circle. MapTiler overlays default to the `streets-v2-dark` raster style with light tile transparency. The map tiles and route use the same frame camera, the current position marker stays centered, and the map/route move underneath it. The compass tape changes with the current movement heading while the map remains north-up.

The full-route overview overlay (`overlay=route`) is a separate transparent layer intended to be composited independently from the local map overlay. It fits the whole workout route into a small panel, draws the full route, the completed route, an optional recent tail, and the current position marker. It does not fetch map tiles, render labels, or use the local autozoom camera. For render performance, dense overview polylines may be thinned for drawing while preserving the route endpoints and marker interpolation.

Overlay bundle responses use one concise summary message with one row per requested overlay. Discord attachments are sent separately only when the files fit attachment limits. If `[public_artifacts]` is configured and files exceed Discord limits, Aimo publishes them under the configured base URL and links them in the summary. Overlay filenames include the workout slug, workout date, rendered distance range, and overlay type. Re-rendering the same public artifact path overwrites the previous file.

Current MVP limitations: GIF output is intended for quick inspection; MOV output is the default transparent editor format; MP4 output is for smaller opaque clips. Heading-up map rotation, richer layouts, and typed natural-language overlay intent are future work. See `docs/OVERLAY_ANIMATION_PLAN.md`.

Validation before rendering:

- workout/workout set belongs to the requester
- dataset exists and contains referenced columns
- required columns have renderable values
- mark/chart kind supports the data shape
- transform and output size are allowed
- `social_image` targets exactly one workout with route points
- `animation_overlay` targets exactly one workout with route and distance samples

Missing primary metrics return a specific localized missing-metric response. Missing secondary metrics may render available series with a note.

### Route Maps

Route maps use `chart_kind=map` and `route`. Python owns point access, projection, tile fetching/caching, attribution, route overlays, route markers, waypoint overlays, elevation overlays, and fallback behavior.

GPX waypoint/reittimerkki annotations are shown on single-route maps by default as map markers and in the route overlay list. The display label prefers GPX `cmt`, then `desc`, then `name`; the marker type may be rendered as an icon from the supported icon font when GPX `type` or `sym` exists. The overlay list shows label plus distance from route start. Multi-route maps hide waypoint overlays to avoid ambiguous clutter. The formal miinustägit `-waypoints` and `-reittimerkit` hide these overlays.

Single-route maps also show kilometer markers using the same distance tick scale as the elevation distance axis. They skip 0 km and finish-distance markers, because those are already implied by the route start and title overlay. Waypoint markers have visual priority over kilometer markers; waypoint labels are placed first and kilometer labels use lower-priority collision avoidance.

Single-route maps also show a bottom elevation overlay when enough distance and elevation samples exist. The overlay is a filled elevation profile with min/max, start/finish, and waypoint vertical markers when they fit. The overlay includes a grade scale, marker labels, graph area, and kilometer axis. Marker labels use simple collision avoidance, and required labels such as start/finish and waypoints have priority over optional min/max labels. The profile is colored by grade difficulty: steep descents are technical, shallow descents are easy, flats are neutral, and climbs progress from yellow to orange to red. Multi-route maps hide this overlay. The formal overlay controls `+overlay:elevation` / `+overlay:korkeus` show it explicitly, and `-overlay:elevation` / `-overlay:korkeus` hide it.

The route title overlay includes distance and, when available, ascent, for example `23.9 km - nousua 276 m`.

Single-route maps include a compact route-time estimate in the title subtitle when Python can calculate one, for example `23.9 km - 276 nm - Ennuste 3 h 17 min`. If the visualization request includes an intended date and route-time intent resolves it, Python may add a weather-adjusted estimate and compact weather facts in the same subtitle, for example `Ennuste 3 h 17 min (20/6/2026, temperature icon 19°C, wind direction icon 3.3m/s, weather icon sade 0%)`. The subtitle renderer uses FontAwesome icons for these weather markers. The map shows only one estimate value; if weather adjustment is available, that adjusted value is shown. Detailed estimate reasoning remains in the conversational route-time estimate/explanation workflow.

MapTiler raster tiles are the preferred configured provider. Local OSM tile rendering is retained as fallback. Aimo draws the route, markers, title, overlays, and optional route coloring itself. API keys must not appear in cache paths, logs, or artifact metadata.

Route data coloring supports one metric at a time, currently HR, elevation, grade, or pace. On route maps, the formal plustägit `+elevation` and `+korkeus` color route segments by absolute elevation. The formal plustägit `+grade`, `+jyrkkyys`, and `+kaltevuus` color route segments with the same grade palette as the elevation overlay, so the same route/profile location has the same climb/descent color. If multiple route color metrics are requested, the first supported one is used and the user gets a deterministic notice.

The formal plustägit `+direction` and `+suunta` add sparse route direction chevrons to route maps. Direction chevrons are opt-in and do not change route color metrics or overlays.

### Deterministic Visualization Controls

Aimo supports two deterministic control forms that are interpreted by Python after the LLM has produced the base intent:

- **Plustägi**: a `+word` override such as `+hr`, `+grade`, `+direction`, `+portrait`, `+poster`, or `+somekuva`. Namespaced plustägit such as `+overlay:elevation` apply a bounded control to a specific visualization overlay.
- **Miinustägi**: a `-word` override such as `-waypoints` or `-reittimerkit`. Namespaced miinustägit such as `-overlay:elevation` disable a specific visualization overlay.
- **Tarkenne**: a `key=value` style/value override such as `dim=45`, `route=white`, or `title=bottom`. Tarkenteet are validated against a small allowed vocabulary and ignored when unknown or invalid.

These controls are intentionally deterministic correction tools. The LLM may see them in the original text, but Python applies the authoritative interpretation.

### Social Images

`social_image` is a shareable single-workout output mode. It defaults to square output and supports aspect tags such as `+portrait` and `+landscape`.

Behavior:

- `+social` or `+somekuva` may force social-image output.
- If the request has a decodable raster image attachment, it is used as a cover-cropped/dimmed background.
- Without an image attachment, the route map background is used.
- The route overlay is decorative over user photos and normalized into a visible overlay region.
- Explicit stat tags control shown stats; otherwise distance, duration, and average HR are shown when available.

Supported deterministic social presets are plustägit: `+classic`, `+minimal`, `+poster`, `+routeonly`, `+data`, and `+photo`.

Bounded tarkenteet may be supplied inline or on a `style:` / `tyyli:` line. Supported style areas are background crop/dim/filter/blur, route color/size/shadow/markers/position, title position/alignment, stats position/style, panel style, text color, accent color, and font family. Invalid or unknown values are ignored; arbitrary renderer instructions are not accepted.

### Debug

`/debug level` returns bounded trace data as ephemeral output. Supported levels are `0`, `1`, and `2`: level 0 is a compact high-value summary, level 1 includes bounded trace events, and level 2 includes the broadest safe redacted Python/LLM interaction details available for the relevant interaction. Non-admins see only traces relevant to themselves; admins may access broader traces.

Mention plustägit `+debug0`, `+debug1`, and `+debug2` request the same levels for that mention interaction and return the debug output to the channel. Debug is always request-scoped; Aimo does not keep a persistent debug mode.

Secrets, raw GPX, image bytes, large raw payloads, full point arrays, and unbounded model payloads must be redacted or summarized even at level 2.

## Error Responses

User-facing deterministic errors should be short, localized, actionable, and non-technical unless debug output is requested. Failures should use typed error categories and stable translation keys.

Examples:

```text
En löytänyt tuolla viitteellä treeniä.
```

```text
Tuo liite ei näytä kelvolliselta GPX-tiedostolta.
```

```text
Treenistä puuttuu tarvittava mittari: heart_rate_bpm.
```
