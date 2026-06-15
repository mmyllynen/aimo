# Production Smoke Test Feedback

This file collects manual production smoke-test feedback before fixes are started.

Rules for this pass:

- Record observations one by one.
- Do not implement fixes during collection.
- Keep enough context to reproduce each issue: time, command/message, expected result, actual result, logs/debug trace if available.
- Start fixes only after the user explicitly says to begin fixing.

## Environment

- Host: mushroom
- Runtime directory: `/home/myllymik/chatgpt`
- Runtime command: `python3 aimo.py --config aimo.conf --run-discord`
- Smoke-test phase started: 2026-06-15

## Feedback Items

### 1. `/aimo apua` UX

- Test/area: slash command help UX
- Current behavior: help is exposed as `/aimo apua:true`, with a boolean `true|false` option.
- Feedback: this is unnecessarily complex. `/aimo apua` should be enough.
- Expected direction: use a simpler command shape for help without requiring a boolean parameter.
- Initial assessment: agreed. A boolean `apua` flag is awkward because the command itself already expresses intent. Better alternatives:
  - make `/aimo apua` a subcommand if Discord command grouping is used;
  - or add a dedicated `/apua`/`/help`-style command;
  - or make `/aimo` with no options show help by default, while `/aimo syote:...` handles text requests.
- Fix applied:
  - Removed the `apua` boolean option from the `/aimo` slash command schema and real Discord command registration.
  - `/aimo` with no useful options now returns help.
  - `/aimo syote:<teksti>` remains the generic text request path.
  - `/aimo liite:<tiedosto>` remains the attachment ingest path and no longer depends on a help flag exception.
  - No backwards-compatibility handling for `apua:true` was kept.
- Status: fixed in code, pending Discord slash command sync/retest after restart.

### 2. `/treenit toiminto:listaa` listing format

- Test/area: workout listing UX
- Current behavior:
  - `Löysin 1 treeniä:`
  - `workout-03916b49-2693-54cc-8258-deed107503bf: Sipoo Running (2026-06-04).`
- Feedback: the internal `workout-<id>` is not useful in the user-facing listing.
- Expected direction: show a compact, user-meaningful list where users can refer to workouts by list number, date, and title/kind instead of opaque ids.
- Suggested format:

```text
Löysin 1 treenin:
1. 4.6.2026 - Sipoo Running
   Juoksu, 8,4 km, 48 min, keskisyke 142
```

- For multiple workouts:

```text
Löysin 3 treeniä:
1. 14.6.2026 - Iltalenkki
   Juoksu, 6,2 km, 36 min, keskisyke 138
2. 12.6.2026 - Työmatkapyöräily
   Pyöräily, 18,5 km, 52 min
3. 10.6.2026 - Sipoo Running
   Juoksu, 8,4 km, 48 min, keskisyke 142

Voit viitata treeniin numerolla, päivämäärällä tai nimellä.
```

- Useful fields, in priority order:
  - list index
  - date
  - title/name
  - activity kind
  - distance
  - duration
  - average HR if available
  - active marker, e.g. `aktiivinen`
- Avoid by default:
  - full internal workout ids
  - long metadata dumps
  - fields missing from the workout
- Initial assessment: agreed. The resolver already supports list-index references, so the list should optimize for `1`, `2`, `viimeisin`, date, and title references rather than exposing UUID-like ids.
- Status: recorded only, no fix started.

### 3. Mention with non-GPX image attachment

- Test/area: mention + unsupported attachment handling
- Test input: mention to Aimo with an image attachment.
- Actual behavior: Aimo answered `Kielimalli ei ole juuri nyt käytettävissä.` in one case.
- Expected behavior: all attachments except `.gpx` activity files or GPX route plans should be rejected deterministically.
- Expected user-facing response direction: a stable unsupported-attachment message, e.g. `Tuen tällä hetkellä vain GPX-tiedostoja.` or existing `error.unsupported_attachment` translation.
- Observed logs/traces:
  - Message received as a real mention with one attachment.
  - Canonical event: `kind=mention`, `attachment_count=1`.
  - Latest failing trace:
    - source event: `1515963371856334949`
    - route: `chat`
    - route reason: `No deterministic skeleton route matched.`
    - workflow: `chat`
    - LLM operation: `chat_reply`
    - LLM result: `LLMGatewayError`
    - outbound localized key: `error.model_unavailable`
  - Another non-GPX image case (`1515963291279691788`) routed to `chat` and produced a normal chat reply instead of rejecting the attachment.
  - GPX attachments correctly route to `gpx_ingest`.
- Current likely cause:
  - `route_event` checks `if event.attachments and _has_gpx_attachment(event)` and routes supported GPX attachments to `GPX_INGEST`.
  - If attachments exist but none is a supported GPX, no deterministic unsupported-attachment branch runs.
  - The event then falls through to LLM/chat routing, which is incorrect for file uploads.
- Initial assessment: this should be deterministic application behavior, not LLM behavior. For any mention/slash request with attachments:
  - if at least one supported GPX is present, route to GPX ingest;
  - if attachments are present but no supported GPX is present, route to a deterministic unsupported-attachment user error;
  - avoid sending image/file metadata or unsupported attachment cases to chat LLM handling.
- Status: recorded only, no fix started.

### 4. Workout analysis mention returns model unavailable

- Test/area: workout chat / latest workout analysis
- Test input:

```text
@aimo analysoi viimeisin treeni
```

- Actual behavior:

```text
Kielimalli ei ole juuri nyt käytettävissä.
```

- Expected behavior: Aimo should analyze the latest workout and answer as a concise coach without asking which workout.
- Observed logs/traces:
  - source event: `1515964064076136598`
  - canonical event: `kind=mention`, `text_chars=25`
  - route: `workout_chat`
  - route reason: `Workout chat request skeleton matched workout language.`
  - repository lookup:
    - `workouts.latest_for_user`: success, returned `WorkoutRecord`
    - `workout_streams.list_streams`: success, returned 5 streams
    - `history.list_recent_for_channel`: success
  - failing LLM operation: `workout_reply`
  - workflow result: `system_error`
  - outbound key: `error.model_unavailable`
- Root cause found with a direct schema probe:

```text
Invalid schema for response_format 'aimo_workout_reply':
In context=('properties', 'claims_used', 'items'), schema must have a 'type' key.
```

- Current likely cause:
  - OpenAI structured outputs require array fields to declare an item type.
  - The current adapter emits array properties with `items: {}`.
  - `chat_reply` works because it has only scalar fields.
  - `workout_reply` fails because `claims_used` and `missing_data_notes` are arrays.
- Expected fix direction:
  - tighten response schemas for array fields, probably `items: {"type": "string"}` for `claims_used`, `missing_data_notes`, and similar operation outputs;
  - update the OpenAI schema adapter to preserve/emit valid item schemas;
  - add tests for OpenAI schema generation with array item types;
  - retest workout reply and visualization intent operations because they also use arrays.
- Status: recorded only, no fix started.

### 5. Workout listing requested via public mention

- Test/area: generic mention chat vs. private workout management
- Test input:

```text
@aimo listaa mun treenit
```

- Actual behavior:

```text
Kielimalli ei ole juuri nyt käytettävissä.
```

- Expected behavior:
  - Do not add a deterministic Python keyword branch for `listaa treenit`.
  - Keep the request on the generic chat/LLM path when no deterministic workflow owns it.
  - The LLM should know Aimo's real capabilities and privacy policy, and should guide the user to `/treenit toiminto:listaa` instead of trying to list private workout data in public chat.
  - The LLM must not invent unsupported external integrations or data sources.
- Observed root cause:
  - The mention routed to generic `chat`.
  - `chat_reply` received only route metadata, not Aimo capability/policy facts.
  - A direct live probe also showed `chat_reply` could return `incomplete` with the old 500-token budget.
- Fix applied:
  - Added generic chat capability facts to the `chat_reply` payload.
  - Tightened the `chat_reply` system prompt to treat capability facts as ground truth and avoid invented integrations/data access.
  - Increased `chat_reply` max tokens from 500 to 2000 to avoid incomplete model responses with current reasoning models.
- Live probe after fix:

```text
En voi listata henkilökohtaisia treenejä tässä julkisessa keskustelussa. Käytä komentoa /treenit toiminto:listaa nähdäksesi omat treenisi (slash-komento, oletuksena yksityinen). Tarvitsetko apua komennon käytössä?
```

- Status: fixed in code, pending Discord smoke retest after restart.

### 6. `/aimo syote` interaction timeout

- Test/area: slash command text request with LLM
- Test input:

```text
/aimo syote:mitä osaat tehdä?
```

- Actual behavior in Discord:

```text
The application did not respond
```

- Observed logs:
  - Interaction was received and dispatched successfully.
  - `chat_reply`/LLM processing took longer than Discord's initial interaction response window.
  - After dispatch finished, sending the first interaction response failed:

```text
discord.errors.NotFound: 404 Not Found (error code: 10062): Unknown interaction
```

- Root cause:
  - Discord slash interactions must be acknowledged quickly.
  - The adapter waited for the full workflow/LLM result before sending the first response.
- Fix applied:
  - Slash interactions are now deferred immediately with `thinking=True`.
  - Workflow output is sent afterwards through the interaction followup channel.
  - This is a generic adapter fix for slow slash workflows, not a special case for `/aimo syote`.
- Status: fixed in code, pending Discord smoke retest after restart.

### 7. Visualization mention returns model unavailable

- Test/area: natural-language workout visualization
- Test input:

```text
@aimo piirrä syke viimeisestä treenistä
```

- Actual behavior:

```text
Kielimalli ei ole juuri nyt käytettävissä.
```

- Observed trace:
  - source event: `1515985609187917894`
  - route: `visualization`
  - route reason: `Visualization request skeleton matched chart language.`
  - failing LLM operation: `visualization_intent`
  - workflow result: `system_error`
  - outbound key: `error.model_unavailable`
- Root cause:
  - OpenAI rejected the `visualization_intent` response schema because nested object fields were not closed:

```text
Invalid schema for response_format 'aimo_visualization_intent':
In context=('properties', 'workout_selector'),
'additionalProperties' is required to be supplied and to be false.
```

- Follow-up issue found during live probe:
  - After the schema was accepted, `visualization_intent` needed the same larger output budget as chat/workout replies to avoid `status='incomplete'`.
  - The first accepted response also used aliases (`most_recent`, `time`, `heart_rate`) instead of Aimo's canonical values.
- Fix applied:
  - OpenAI schema generation now handles nested object `properties`, `required`, and `additionalProperties` recursively.
  - `visualization_intent` now uses closed nested objects for `workout_selector` and `date_range`.
  - `visualization_intent` now restricts selector, metric, and transform values to canonical enums.
  - `visualization_intent` max tokens increased from 500 to 2000.
- Live probe after fix:

```text
workout_selector {'type': 'latest', 'value': '', 'count': None, 'limit': None}
x_metric elapsed_s
y_metrics ('heart_rate_bpm',)
transforms ()
date_range {'start': '', 'end': ''}
comparison_mode
```

- Status: fixed in code, pending Discord smoke retest after restart. Rendering may still reveal a separate issue after intent extraction succeeds.

### 8. Visualization chart lacks title, readable axes, and scale labels

- Test/area: rendered workout visualization layout
- Test input:

```text
@aimo piirrä syke viimeisestä treenistä
```

- Actual behavior after intent fix:
  - Chart rendered successfully.
  - Image had no title/subtitle.
  - Axes had no labels or tick values.
  - Y scale was raw data-bound, so readability depended on the exact data range.
- Expected behavior:
  - Rendered chart should include a clear title.
  - Subtitle should summarize workout context compactly.
  - Axes should show labels, tick values, and readable gridlines.
  - Numeric scale should be derived generically from visible data ranges using rounded "nice" values.
  - Single-series charts do not need a legend when title/y-axis already identify the series.
- Fix applied:
  - Added generic chart layout with title, subtitle, axis labels, gridlines, and optional legend.
  - Added generic numeric axis scaling with nice-number ticks.
  - Example data range `89..143` now scales to `80..150`.
  - Tick labels are whole numbers unless the data scale requires decimals.
  - Time x-axis values render as durations such as `0:00`, `10:00`, `20:00`.
  - Added a small internal bitmap text renderer; no new production dependency was introduced.
- Status: fixed in code, pending Discord smoke retest after restart.

### 9. Long LLM call blocks Discord heartbeat

- Test/area: Discord runtime behavior during slow LLM-backed mention handling
- Test input:

```text
@aimo piirrä syke viimeisestä treenistä
```

- Actual behavior:
  - A previous visualization request succeeded.
  - A later retry returned `Kielimalli ei ole juuri nyt käytettävissä.`
  - Logs showed Discord heartbeat blockage while waiting for OpenAI:

```text
Shard ID None heartbeat blocked for more than 30 seconds.
```

- Observed trace:
  - workflow: `visualization`
  - failing operation: `visualization_intent`
  - LLM duration: about 30037 ms
  - result: `system_error`
- Root cause:
  - Discord async handlers ran the synchronous dispatcher directly in the event loop.
  - The OpenAI HTTP client also had a 30s timeout, so even after event-loop isolation the request would still be cut off at 30s.
- Fix applied:
  - Discord message and interaction handlers now run workflow dispatch in a worker thread with `asyncio.to_thread`.
  - Worker dispatch opens its own SQLite connection, so the main runtime connection is not shared across threads.
  - Slash commands still defer immediately before worker dispatch.
  - OpenAI HTTP timeout is now configurable as `[openai] timeout_s`, default `180`.
  - No deterministic intent fallback was added; LLM remains responsible for natural-language intent.
- Status: fixed in code, pending Discord smoke retest after restart.

### 10. Dense chart line looks too thick

- Test/area: rendered workout visualization style
- Actual behavior:
  - Dense line charts looked thick and blocky.
  - Cause: renderer drew both connecting line segments and square markers for every point.
- Expected behavior:
  - Dense time series should render as a clean line without point markers.
  - Sparse series may still show markers.
  - Background can be more polished if it remains subtle and does not reduce readability.
- Fix applied:
  - Added generic marker visibility rule based on visible point count.
  - Dense series above 80 visible points render without markers.
  - Sparse series still render markers.
  - Added a subtle neutral vertical gradient background for all chart types.
  - No metric-specific rule was added.
- Status: fixed in code, pending Discord smoke retest after restart.

### 11. Multi-series chart with outlier flattens one scaled series

- Test/area: multi-series workout visualization with scaled metrics
- Test input:

```text
@aimo piirrä samaan kuvaajaan syke, vauhti ja korkeuskäyrä viimeisimmästä treenistä
```

- Actual behavior:
  - Chart rendered with three series.
  - Heart rate and elevation were readable.
  - Pace was mostly flat because one large outlier dominated the scaled domain.
  - Multi-series title rendered awkwardly as the first metric plus count.
  - Legend used raw metric ids such as `PACE_S_PER_KM`.
- Expected behavior:
  - Multi-series title should be generic, e.g. `Workout metrics - <title>`.
  - Legend should use human-readable metric names.
  - Scaled series should use robust render-domain handling so one outlier does not flatten the visible series.
  - Outlier clipping must affect only rendering, not stored data or analysis.
- Fix applied:
  - Multi-series charts now use a generic `Workout metrics - <title>` title.
  - Legend labels use readable metric names and annotate `scaled` / `clipped`.
  - Normalized secondary series use a generic robust domain based on percentiles when outliers substantially widen the full range.
  - Values outside the robust render domain are clipped only for drawing.
  - No metric-specific rule was added.
- Status: fixed in code, pending Discord smoke retest after restart.

### 12. Multi-unit line metrics should default to small multiples

- Test/area: multi-series workout visualization layout
- Test input:

```text
@aimo piirrä samaan kuvaajaan syke, vauhti ja korkeuskäyrä viimeisimmästä treenistä
```

- Actual behavior after robust scaling fix:
  - Chart rendered all three metrics on one y-axis.
  - Pace became noisy vertical spikes and was not readable.
- Expected behavior:
  - Multiple line metrics with different units should default to separate panels in the same image.
  - A shared single y-axis should be used only when the user explicitly asks for the same y-axis, same scale, or overlaid series.
  - The rule must be generic: based on layout intent and metric units, not on hard-coded heart-rate/pace/elevation special cases.
- Fix applied:
  - Visualization intent now includes `layout_mode`: `auto`, `single_axis`, or `small_multiples`.
  - LLM instructions clarify that Finnish `samaan kuvaajaan` means the same image, not automatically one y-axis.
  - `auto` layout renders line metrics with different units as small multiples in one PNG.
  - Explicit `single_axis` or `normalize_to_primary_range` still uses the combined/scaled path.
  - Small-multiple panels use individual y-axes and a shared x-axis.
- Status: fixed in code, pending Discord smoke retest after restart.

### 13. Pace outlier breaks small-multiple chart scale

- Test/area: small-multiple workout visualization with point-level pace
- Actual behavior:
  - The pace panel y-axis scaled to about `0...300000`.
  - The pace series became unreadable except for one huge spike.
- Analysis:
  - The renderer was showing stored point-level `pace_s_per_km` values as-is.
  - The extreme value likely comes from GPX-derived point pace where elapsed time is divided by a very short point-to-point distance.
  - The chart did not create the value, but it allowed the outlier to define the pane's y-axis.
- Fix applied:
  - Line charts now use a conservative generic IQR-based render domain.
  - Clipping activates only when full range exceeds `10 * IQR`; fences are `Q1 - 6 * IQR` and `Q3 + 6 * IQR`.
  - Points outside the robust render domain are omitted from drawing only for that chart/panel.
  - Dense rough series are automatically smoothed for rendering when they have at least 120 visible points and roughness ratio is at least `0.35`.
  - Short internal gaps created by clipped outliers are linearly bridged before smoothing, up to the smoothing window size.
  - Line chart y-axes are calculated from the final render series after clipping/smoothing, so smoothed views do not keep an unnecessarily wide raw-data axis.
  - Time-per-distance metrics use inverted y-axis semantics so faster values render higher while other metrics keep normal orientation.
  - Inverted y-axis semantics apply to both series drawing and y-axis tick/grid placement.
  - Explicit `rolling_average` smoothing uses a data-size-aware window, currently capped at 61 points for long dense series.
  - Explicit `rolling_average` requests still smooth regardless of the automatic thresholds.
  - Clipped and smoothed series are marked in chart labels/legends.
  - Pace y-axis ticks are formatted as `min:sec` per kilometer while stored values remain `s/km`.
  - No stored workout data is changed.
- Follow-up:
  - GPX ingest pace derivation should later be stabilized so new point-level pace streams do not generate extreme values from near-zero point distances.
- Status: fixed in code, pending Discord smoke retest after restart.
