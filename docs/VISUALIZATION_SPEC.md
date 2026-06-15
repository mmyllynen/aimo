# Aimo v3 Visualization Spec

## Goal

Aimo turns natural-language workout visualization requests into rendered image files.

The visualization pipeline must be reliable, bounded, and deterministic after initial language interpretation.

## Supported User Requests

Examples:

```text
piirrä viimeisimmästä treenistä syke ajan funktiona
```

```text
piirrä viimeisimmästä treenistä syke, vauhti ja korkeus samaan kuvaajaan, vauhti ja korkeus skaalattuna sykkeen alueelle
```

```text
näytä kuluvan kuukauden sykevyöhykejakauma
```

```text
vertaa kahta viimeisintä juoksua
```

```text
piirrä reitin korkeuskäyrä
```

## Architecture Principle

Aimo is a generic workout visualizer.

The implementation must not grow by adding workflow-specific branches for each new chart request. Rendering marks are primitives, not product features. Product behavior is expressed through a validated visualization spec that references resolved datasets.

Required boundary:

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

Python owns:

- dataset resolution
- workout ownership checks
- metric alias resolution
- manifest generation
- spec validation
- transform execution
- rendering

The language model may help interpret user text and propose a bounded spec, but only from compact manifests. It must not receive raw workout point rows, raw GPX, secrets, or user-private data that is not required for the requested visualization.

## Pipeline

1. Route request to visualization workflow.
2. Extract visualization intent from user text.
3. Compile a dataset request.
4. Resolve datasets and workout selectors with owner checks.
5. Build a compact dataset manifest.
6. Produce a visualization spec from the intent and manifest.
7. Validate and compile the spec.
8. Fetch or use raw series internally only after validation.
9. Apply transforms in Python.
10. Render image through renderer adapter.
11. Send image and concise caption.

## Visualization Intent

Visualization intent is semantic and small. It is not the final render instruction.

Fields:

- `workout_selector`
- requested datasets
- requested metrics
- grouping hints
- `date_range`
- transform hints
- `comparison_mode`
- `caption_preference`

Visualization intent must not contain raw point rows.

## Workout Selectors

Supported selectors:

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

## Supported Metrics

Canonical metric ids:

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

Metric aliases:

- `syke`, `heart_rate`, `hr` -> `heart_rate_bpm`
- `vauhti`, `pace` -> `pace_s_per_km`
- `korkeus`, `maasto`, `elevation`, `altitude` -> `elevation_m`
- `aika`, `time` -> `elapsed_s` for workout point charts
- `matka`, `distance` -> `distance_km`
- `kadenssi`, `cadence` -> `cadence_spm`

Alias resolution is deterministic and owned by Python.

## Dataset Request

Dataset request is the deterministic Python-owned description of what data is needed.

Fields:

- dataset ids
- dataset source type:
  - workout points
  - workout streams
  - workout summary
  - HR zones
  - workout collection
- owner user id
- workout selector
- date range
- requested metrics
- requested dimensions
- comparison scope

Dataset request may be derived from LLM output, but Python validates and normalizes it before repository access.

## Dataset Manifest

Dataset manifest is the only dataset description the model may see for visualization planning.

Fields:

- dataset id
- row count
- available columns
- canonical metric ids
- unit
- semantic type:
  - quantitative
  - temporal
  - ordinal
  - nominal
- null count
- min/max for safe numeric fields
- allowed transforms
- allowed grouping dimensions

Dataset manifest must not contain raw rows.

## Visualization Spec

Visualization spec is concrete and validated before rendering.

Fields:

- datasets
- mark:
  - line
  - point
  - bar
  - area
  - interval
  - arc
- encodings:
  - x
  - y
  - color
  - group
  - size
- transforms
- filters
- aggregation
- sorting
- scale policy
- annotations
- legend
- layout
- output filename

Visualization spec references only dataset ids and canonical column ids.

## Rendering Marks

V1 supported:

- `line`
- `point`
- `bar`
- `area`
- `interval`
- `arc`

Common use:

- `line`: time series, HR, pace, elevation
- `point`: relationships between two metrics
- `bar`: workout summaries and comparisons
- `area`: cumulative or filled trend
- `interval`: distributions and bins
- `arc`: part-to-whole distributions such as HR zones

Unsupported marks should return a user-level unsupported request or fall back to a close supported mark when safe.

## Transforms

Supported V1 transforms:

- `normalize_to_primary_range`
- `smooth`
- `rolling_average`
- `aggregate_sum`
- `aggregate_avg`
- `filter_non_null`

### Normalize To Primary Range

Used when user asks to scale multiple metrics into the same visible range.

Policy:

- first requested y metric is primary unless otherwise specified
- primary series keeps original values
- secondary series are linearly scaled to primary min/max
- caption or legend should indicate scaled series

## Missing Data Policy

If requested metric is missing:

- If primary metric is missing, return a specific missing metric message.
- If secondary metric is missing, render available series and note missing metric.
- If no requested metric exists, return a specific error.

Do not ask "which workout?" when the selected workout is explicit but lacks data.

## Validation Rules

Before rendering:

- workout belongs to requesting user
- dataset exists
- spec references existing dataset ids
- encodings reference existing columns
- required columns have renderable values
- mark supports requested data shape
- transforms are allowed for metric types
- aggregation is allowed for selected metric and grouping
- output size is within limits

## Caption Requirements

Caption should be short and include:

- selected workout/date when useful
- important missing data note
- scaled-series note if normalization was applied

Do not include internal plan JSON or model reasoning.

## Image Requirements

- PNG output for v1
- non-empty render
- stable dimensions
- readable labels
- legend when multiple series exist
- no raw data dump in the message
