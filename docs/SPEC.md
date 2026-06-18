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

Current-workout context is internal workflow state. It is updated by GPX ingest, deterministic workout commands, or explicit structured LLM `context_update` fields after safe single-workout resolution.

### Visualization

Aimo turns natural-language workout visualization requests into PNG artifacts.

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

Validation before rendering:

- workout/workout set belongs to the requester
- dataset exists and contains referenced columns
- required columns have renderable values
- mark/chart kind supports the data shape
- transform and output size are allowed
- `social_image` targets exactly one workout with route points

Missing primary metrics return a specific localized missing-metric response. Missing secondary metrics may render available series with a note.

### Route Maps

Route maps use `chart_kind=map` and `route`. Python owns point access, projection, tile fetching/caching, attribution, route overlays, route markers, waypoint overlays, elevation overlays, and fallback behavior.

GPX waypoint/reittimerkki annotations are shown on single-route maps by default as map markers and in the route overlay list. The display label prefers GPX `cmt`, then `desc`, then `name`; the marker type may be rendered as an icon from the supported icon font when GPX `type` or `sym` exists. The overlay list shows label plus distance from route start. Multi-route maps hide waypoint overlays to avoid ambiguous clutter. The formal miinustägit `-waypoints` and `-reittimerkit` hide these overlays.

Single-route maps also show kilometer markers using the same distance tick scale as the elevation distance axis. They skip 0 km and finish-distance markers, because those are already implied by the route start and title overlay. Waypoint markers have visual priority over kilometer markers; waypoint labels are placed first and kilometer labels use lower-priority collision avoidance.

Single-route maps also show a bottom elevation overlay when enough distance and elevation samples exist. The overlay is a filled elevation profile with min/max, start/finish, and waypoint vertical markers when they fit. The overlay includes a grade scale, marker labels, graph area, and kilometer axis. Marker labels use simple collision avoidance, and required labels such as start/finish and waypoints have priority over optional min/max labels. The profile is colored by grade difficulty: steep descents are technical, shallow descents are easy, flats are neutral, and climbs progress from yellow to orange to red. Multi-route maps hide this overlay. The formal miinustägit `-elevation` and `-korkeus` hide it.

The route title overlay includes distance and, when available, ascent, for example `23.9 km - nousua 276 m`.

MapTiler raster tiles are the preferred configured provider. Local OSM tile rendering is retained as fallback. Aimo draws the route, markers, title, overlays, and optional route coloring itself. API keys must not appear in cache paths, logs, or artifact metadata.

Route data coloring supports one metric at a time, currently HR, elevation, or pace. If multiple route color metrics are requested, the first supported one is used and the user gets a deterministic notice.

### Deterministic Visualization Controls

Aimo supports two deterministic control forms that are interpreted by Python after the LLM has produced the base intent:

- **Plustägi**: a `+word` override such as `+hr`, `+portrait`, `+poster`, or `+somekuva`. Plustägit add metrics, output modes, aspect ratios, and bounded presets.
- **Miinustägi**: a `-word` override such as `-waypoints`, `-reittimerkit`, `-elevation`, or `-korkeus`. Miinustägit disable or remove something that would otherwise be shown by default.
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

`/debug` returns bounded trace data as restricted output. Non-admins see only traces relevant to themselves; admins may access broader traces. Secrets, raw GPX, large raw payloads, full point arrays, and unbounded model payloads must be redacted or summarized.

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
