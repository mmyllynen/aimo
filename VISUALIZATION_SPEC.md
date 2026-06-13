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

## Pipeline

1. Route request to visualization workflow.
2. Extract chart intent from user text.
3. Resolve workout selector.
4. Build dataset manifest from available data.
5. Produce or compile render plan.
6. Validate render plan.
7. Fetch raw series internally.
8. Apply transforms.
9. Render image.
10. Send image and concise caption.

## Chart Intent

Chart intent is semantic and small.

Fields:

- `workout_selector`
- `chart_family`
- `x_metric`
- `y_metrics`
- `group_by`
- `date_range`
- `transforms`
- `comparison_mode`
- `caption_preference`

Chart intent must not contain raw point rows.

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

## Chart Families

V1 supported:

- `line`
- `scatter`
- `bar`
- `area`
- `pie`
- `histogram`

Common use:

- `line`: time series, HR, pace, elevation
- `scatter`: relationship between two metrics
- `bar`: workout summaries and comparisons
- `area`: cumulative or filled trend
- `pie`: part-to-whole distributions such as HR zones
- `histogram`: metric distributions

Unsupported chart families should return a user-level unsupported request or fall back to a close supported family when safe.

## Render Plan

Render plan is concrete and validated.

Fields:

- datasets
- series
- x axis
- y axes or scale policy
- transforms
- annotations
- legend
- layout
- output filename

Render plan references only canonical column ids.

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
- series references existing columns
- x and y columns have renderable values
- chart family supports requested data shape
- transforms are allowed for metric types
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

