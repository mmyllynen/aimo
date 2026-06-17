# Aimo Visualization Spec

## Goal

Aimo turns natural-language workout visualization requests into rendered PNG image files.

The visualization pipeline is deterministic after language interpretation: Python owns data access, ownership checks, canonical ids, spec validation, transforms, and rendering.

The implementation must stay generic. New visualization capability is added as reusable datasets, column metadata, transforms, marks, encodings, validators, or renderer primitives. Do not add metric-specific or use-case-specific Python branches such as a dedicated heart-rate chart path. Heart-rate-zone distribution, workout comparisons, and future distributions should all flow through the same dataset/manifest/spec/mark machinery.

The LLM is the interpretation layer: it maps user language to selectors, metrics, transforms, chart kind, and layout hints from bounded context. Python is the engine: it validates the spec, resolves data safely, runs generic transforms, and renders generic marks. Python should not grow open-ended `if user asked X then draw Y this special way` logic.

Follow-up visualization requests may use previous visualization context. Python may provide that context for every visualization request when it is safely available; the LLM decides whether the user's language refers to it. The context must be compact: previous intent/spec metadata, selected workout ids, chart kind, layout, transforms, and rendered metric ids. It must be scoped at least by owner and preferably by owner plus channel. It must not include raw GPX, raw point rows, image bytes, or unrelated channel history. A follow-up produces a complete new generic intent/spec and then goes through the same validation/rendering pipeline.

## Supported Requests

Examples:

```text
piirrä viimeisimmästä treenistä syke ajan funktiona
```

```text
piirrä viimeisimmästä treenistä syke, vauhti ja korkeus samaan kuvaajaan
```

```text
näytä sykevyöhykejakauma
```

```text
vertaa kahta viimeisintä juoksua
```

## Pipeline

```text
natural language
-> visualization intent
-> dataset request
-> dataset resolver
-> dataset manifest
-> visualization spec
-> validator/compiler
-> renderer adapter
-> PNG artifact
```

The model may help interpret user text and propose a bounded spec from compact manifests. It must not receive raw workout point rows, raw GPX, secrets, or unrelated private data.

Pipeline stages must not bypass each other for specific chart requests. If a request cannot be represented by the current generic spec, add the missing generic primitive or return an unsupported/invalid-plan response.

If model output cannot be compiled into a supported spec, Python may make one bounded revision request to the LLM. The revision input contains the original user text, the failed intent/spec metadata, compact dataset manifest, allowed generic primitives, and structured validation errors. It must not include raw rows, GPX, image bytes, stack traces, or workflow internals. The LLM must return a complete replacement intent/spec. Python validates the replacement through the same compiler; a second failure returns a controlled invalid-plan response.

## Selectors

Supported workout selectors:

- latest
- active
- explicit workout id
- list index
- date
- date range
- tag
- workout kind/type
- recent N

Explicit latest/active/specific selectors must not trigger generic workout-choice clarification.

## Metrics

Canonical metric ids include:

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

Common language aliases are interpreted by the LLM and must be returned to Python as canonical metric ids:

- `syke`, `heart_rate`, `hr` -> `heart_rate_bpm`
- `vauhti`, `pace` -> `pace_s_per_km`
- `korkeus`, `elevation`, `altitude` -> `elevation_m`
- `aika`, `time` -> `elapsed_s` for point charts
- `matka`, `distance` -> `distance_km`
- `kadenssi`, `cadence` -> `cadence_spm`
- `reitti`, `route`, `kartta`, `map` -> `route` with `chart_kind=map`
- `somekuva`, `social image`, `share image` -> `output_mode=social_image` with one workout and `route`

Python does not infer metrics, transforms, chart types, or previous-chart references from natural-language substrings.

## Dataset Manifest

The manifest is the model-visible dataset description.

It may include:

- dataset id
- row count
- available columns
- units
- semantic types
- null counts
- safe min/max stats
- allowed transforms
- allowed grouping dimensions

It must not include raw rows.

## Visualization Spec

The spec references only dataset ids and canonical column ids.

Fields:

- datasets
- mark
- encodings
- transforms
- filters
- aggregation
- sorting
- scale policy
- annotations
- legend
- layout
- output filename

Supported marks:

- `line`
- `bar`
- `pie`

Supported chart kinds:

- `auto`
- `line`
- `bar`
- `pie`
- `map`

Supported output modes:

- `chart`
- `social_image`

Supported transforms:

- `normalize_to_primary_range`
- `smooth`
- `rolling_average`
- `aggregate_sum`
- `aggregate_avg`
- `as_percentage_of_total`
- `filter_non_null`

## Missing Data

- Missing primary metric: return a specific missing-metric message.
- Missing secondary metric: render available series and note the missing metric.
- No requested metric exists: return a specific error.

Do not ask which workout the user meant when the selected workout is explicit but lacks data.

## Validation

Before rendering:

- workout belongs to requesting user
- dataset exists
- spec references existing dataset ids
- encodings reference existing columns
- required columns have renderable values
- mark supports the data shape
- transforms are allowed for selected metric types
- chart kind is one of the supported generic chart kinds
- `social_image` targets exactly one workout
- output size is within limits

## Rendering

The deterministic application selects the concrete renderer from `[renderers]` config. Supported renderer names are `internal` and `pillow`; chart-specific settings for `line`, `multi_panel_line`, `bar`, `pie`, `route`, and `social_image` override `default` when set. The default renderer is `pillow`; set `internal` explicitly to use the dependency-free fallback. The LLM does not choose the renderer.

All chart types use the same renderer frame:

- a readable title and compact workout subtitle
- one plot area for the mark
- one fixed right sidebar for legends and per-series/category values; the sidebar background extends to the top, bottom, and right image edges while content keeps internal padding
- a subtle background gradient that must not reduce contrast
- shared tick, duration, pace, and percentage value formatting
- generic supersampling/downsampling antialiasing for rendered marks and chart edges
- native-resolution text overlay after downsampling so title, axes, ticks, labels, and legend text stay crisp
- 1920x1080 default output for HD social sharing unless a chart model explicitly overrides dimensions

Legend content is driven by render metadata, not chart-specific text assembly. Percentage values are shown once, for example `PK1 12.5%`, not as duplicate value/share pairs. Categorical zero-value rows remain renderable legend entries when they are part of the resolved dataset, even if the mark itself has no visible geometry for zero.

Color is generic metadata. Datasets may expose optional `color_hint` values such as named palette entries or hex RGB values; renderers may use them for any categorical bar or pie chart. Python must not infer colors from natural-language user text or add metric-specific color branches. If no hint exists, the renderer uses the shared default palette.

The `internal` dependency-free bitmap renderer is retained as a fallback. The `pillow` renderer may be used for all chart types and is preferred for route maps when high-quality tile stitching, crop, resize, and overlay antialiasing are needed. Title, subtitle, axes, ticks, labels, and sidebar entries must use stable layout constraints so new data does not resize or overlap the chart frame.

`social_image` is a shareable single-workout output mode. It defaults to a square output, supports aspect overrides such as `+portrait` and `+landscape`, uses an attached raster image as a cover-cropped and slightly dimmed background when present, and otherwise uses the route map background. The route overlay is decorative when drawn over a user image; it is normalized into a visible overlay region rather than georeferenced to the photograph. If explicit stat metrics are present, only those stats are shown; otherwise the default stats are distance, duration, and average heart rate when available. Deterministic plus tags may force the output mode with `+social` or `+somekuva` and may select stats such as `+distance`, `+duration`/`+kesto`, `+hr`, `+maxhr`, `+ascent`/`+nousumetrit`, `+pace`, and `+date`.

## Output

- PNG image.
- Short caption.
- Readable labels and legend when needed.
- Note scaled secondary series.
- No raw data dump.
