# Aimo Period Analysis And Visualization Plan

## Purpose

This document defines a planned feature area for week/month/date-range workout summaries and visualizations.

The goal is to let users ask questions such as:

```text
miten viime viikko meni?
```

```text
tee yhteenveto tästä kuusta
```

```text
visualisoi viime kuukauden treenit viikoittain
```

```text
show my training volume for the last four weeks
```

The same period model should support both:

- prose feedback and analysis
- requested visualizations

The implementation must preserve Aimo's existing architecture:

- LLM interprets language and writes prose.
- Python resolves dates, ownership, data access, aggregation, validation, rendering, permissions, and errors.
- Raw GPX and full point arrays are not sent to model planning inputs.
- Period features are generic; avoid Python branches such as "weekly distance chart" or "monthly HR chart".

## Product Behavior

Period analysis should answer at a practical coaching level:

- how much the user trained in the selected period
- whether the period was steady, sparse, or clustered
- what changed compared with adjacent periods when requested
- which data is missing
- one concise next observation or next-step suggestion

The bot should not invent unavailable facts. If heart-rate data or zones are missing, it should say so plainly and continue with distance, duration, count, ascent, or available metrics.

## User Surfaces

### Natural Language

The primary surface is mention-based natural language:

```text
@Aimo miten viime viikko meni?
@Aimo vertaa tätä kuukautta viime kuuhun
@Aimo piirrä viime kuukauden treenit viikoittain
@Aimo näytä viimeisen 30 päivän treenimäärä
```

Routing may classify these into either a period-analysis workflow or the existing visualization workflow, depending on the requested output mode.

### Slash Commands

Slash commands are optional for the MVP but useful for deterministic access.

Candidate commands:

```text
/treenit yhteenveto jakso: viikko|kuukausi|30pv
/treenit yhteenveto alku: YYYY-MM-DD loppu: YYYY-MM-DD
```

Visualizations may remain primarily natural-language driven at first. A slash command for charts should only be added if it can stay generic, for example:

```text
/treenit visualisoi jakso: kuukausi ryhmitys: viikko mittari: distance_km
```

## Conceptual Model

Period requests have four separable parts:

- period selector: which time range to analyze
- grouping: whether rows are bucketed by day, week, month, or not bucketed
- metrics: which canonical measurements matter
- output mode: prose, visualization, or both

The LLM may infer these from language. Python owns the actual resolution and execution.

Example semantic intent:

```json
{
  "period_selector": {
    "kind": "relative_period",
    "value": "last_week"
  },
  "grouping": "day",
  "metrics": ["workout_count", "distance_km", "duration_s"],
  "comparison": {
    "mode": "previous_period"
  },
  "output_mode": "prose"
}
```

## LLM Contract

Add a typed operation for period intent interpretation, or extend the visualization intent contract with equivalent fields.

Suggested operation: `interpret_period_request`.

Input:

- user text
- configured language
- current date/time and timezone
- compact routing context
- allowed period selector kinds
- allowed grouping values
- allowed canonical metrics
- allowed output modes

Forbidden input:

- raw GPX
- workout point rows
- full channel history
- secrets
- unrelated users' data

Output:

```text
period_selector
grouping
metrics
comparison
filters
output_mode
chart_kind
reason
```

Allowed `period_selector.kind` values:

- `current_week`
- `last_week`
- `current_month`
- `last_month`
- `rolling_days`
- `date_range`
- `calendar_year_to_date`

Allowed `grouping` values:

- `none`
- `day`
- `week`
- `month`

Allowed `comparison.mode` values:

- `none`
- `previous_period`
- `same_period_previous_month`
- `same_period_previous_year`

Allowed `output_mode` values:

- `prose`
- `visualization`
- `both`

Rules:

- The LLM returns semantic intent only.
- The LLM does not calculate dates unless the user gave explicit dates.
- Python normalizes relative periods using the configured timezone and current date.
- Python may reject unsupported combinations with typed user errors.
- If the request asks for a chart, the intent must still be convertible into the generic visualization dataset/spec pipeline.

## Period Resolution

Python should resolve period selectors deterministically.

Rules:

- Use the configured bot/user timezone where available; otherwise use config default.
- Calendar weeks should have a documented week start. For Finland-oriented defaults, Monday is reasonable.
- `current_week` means the calendar week containing the request date.
- `last_week` means the complete calendar week before the current week.
- `current_month` means the calendar month containing the request date, from day 1 through request date or full month depending on policy.
- `last_month` means the complete previous calendar month.
- `rolling_days` uses an integer day count and ends at the request date/time.
- `date_range` requires valid start and end dates, inclusive.

Open decision:

- For `current_week` and `current_month`, decide whether to include only elapsed time up to "now" or the full calendar period. MVP should include elapsed time up to the request time and label the period clearly.

## Repository Support

Add owner-scoped workout queries for period features.

Candidate repository method:

```python
list_for_user_in_period(
    owner_user_id: str,
    *,
    start_time_utc: str,
    end_time_utc: str,
    kind: str | None = None,
) -> tuple[WorkoutRecord, ...]
```

Ordering:

- newest first for lists
- chronological order for aggregation inputs

Resolution:

- Prefer `start_time_utc` when available.
- Fall back to `created_at` only when the workout has no start time.
- Ownership must be enforced in the SQL query.

## Aggregation Service

Introduce a deterministic period aggregation service outside workflows and outside visualization rendering.

Candidate module:

```text
workout/periods.py
```

Responsibilities:

- resolve period selectors into concrete UTC start/end bounds
- bucket workouts by day/week/month
- aggregate scalar workout fields
- calculate missing-data facts
- calculate optional HR-zone summaries when points and zones are explicitly needed
- produce compact facts for prose and rows for datasets

The service should not call the LLM and should not render charts.

## Generic Period Datasets

Add datasets that can be consumed by the existing visualization manifest/spec/compiler/renderer model.

### `workout_period_summary`

One row for the whole selected period.

Candidate columns:

- `period_start`
- `period_end`
- `workout_count`
- `distance_km`
- `duration_s`
- `ascent_m`
- `avg_duration_s`
- `avg_distance_km`
- `avg_hr_bpm`
- `max_hr_bpm`
- `easy_duration_s`
- `moderate_duration_s`
- `hard_duration_s`

### `workout_period_buckets`

One row per day/week/month bucket.

Candidate columns:

- `bucket_start`
- `bucket_end`
- `bucket_label`
- `workout_count`
- `distance_km`
- `duration_s`
- `ascent_m`
- `avg_hr_bpm`
- `max_hr_bpm`
- `easy_duration_s`
- `moderate_duration_s`
- `hard_duration_s`

### `workout_period_workouts`

One row per workout in the selected period.

Candidate columns:

- `workout_id`
- `workout_title`
- `local_date`
- `start_time_utc`
- `primary_kind`
- `distance_km`
- `duration_s`
- `pace_s_per_km`
- `ascent_m`
- `avg_hr_bpm`
- `max_hr_bpm`
- `point_count`

These datasets should expose manifests with row counts, column metadata, null counts, safe min/max values, allowed transforms, and grouping dimensions. They must not expose raw point rows.

## Prose Analysis

Add a typed LLM operation for period prose after deterministic aggregation.

Suggested operation: `write_period_analysis`.

Input:

- user text
- configured language
- resolved period label and bounds
- aggregate facts
- bucket summaries
- optional comparison facts
- missing data facts
- allowed claim boundaries

Forbidden input:

- raw GPX
- full point rows
- secrets
- unrelated channel history

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules:

- Keep the reply concise.
- Mention the period explicitly.
- Use only provided facts.
- State missing data plainly.
- Include at most one next-step suggestion unless the user asks for more.
- Avoid medical or overconfident recovery claims.

## Visualization Flow

Period visualizations should reuse the existing pipeline:

```text
natural language
-> period/visualization intent
-> concrete period resolution
-> owner-scoped workout query
-> generic period dataset manifest
-> visualization spec
-> validation/compiler
-> renderer
-> PNG artifact
```

The LLM chooses generic chart primitives from the manifest:

- mark: `line`, `bar`, or `pie`
- x: e.g. `bucket_label`, `bucket_start`, or `workout_title`
- y: canonical period metric ids
- transforms: e.g. `aggregate_sum`, `aggregate_avg`, `as_percentage_of_total`

Python must not special-case chart requests by phrase. If the manifest/spec cannot represent the request, add a generic primitive or return a controlled unsupported/invalid-plan response.

## MVP Scope

Implement the smallest useful version in this order:

1. Period resolution for `last_week`, `current_week`, `last_month`, `current_month`, and `rolling_days`.
2. Owner-scoped repository query for workouts in a period.
3. Aggregation service for count, total distance, total duration, total ascent, average HR, max HR, longest workout, and missing data facts.
4. `write_period_analysis` fakeable LLM operation.
5. Natural-language routing for prose requests such as "miten viime viikko meni".
6. Tests for period resolution, repository ownership, aggregation, workflow behavior, and fake LLM output.

MVP can skip:

- HR-zone duration aggregation across period
- period comparison
- slash commands
- visualization

## Visualization Follow-Up Scope

After prose MVP:

1. Add `workout_period_buckets` and `workout_period_workouts` datasets.
2. Extend visualization intent so period selectors and groupings are first-class.
3. Compile period manifests into generic bar/line charts.
4. Support requests like:

```text
visualisoi viime viikon treenit päivittäin
näytä tämän kuun matka viikoittain
piirrä viimeisen 30 päivän treenimäärä
```

Initial supported visual metrics:

- `workout_count`
- `distance_km`
- `duration_s`
- `ascent_m`

Later metrics:

- `avg_hr_bpm`
- `max_hr_bpm`
- `easy_duration_s`
- `moderate_duration_s`
- `hard_duration_s`

## Comparison Follow-Up Scope

Add previous-period comparison after the core period model is stable.

Examples:

```text
vertaa tätä viikkoa viime viikkoon
oliko tämä kuukausi kovempi kuin viime kuukausi?
```

Python should produce comparison facts:

- absolute delta
- percentage delta when denominator is meaningful
- missing metric notes
- period labels and bounds

The LLM should explain the comparison without inventing causal claims.

## Error Handling

User-facing errors should be typed and localized.

Candidate cases:

- no workouts in period
- invalid date range
- period too large
- unsupported grouping
- unsupported metric
- missing requested metric
- model unavailable for prose
- invalid visualization plan

Best-effort behavior:

- If some metrics are missing, continue with available metrics and include a missing-data note.
- If no workouts exist in the selected period, return a concise "no workouts found" response with the resolved period label.
- If the user asks for a chart metric unavailable in all rows, return a specific missing-metric response.

## Privacy And Safety

- Only the requesting user's workouts are included.
- No raw GPX is sent to LLM operations.
- Full point arrays are not sent to model planning or prose operations.
- Period analysis should be based on stored facts and optional deterministic zone summaries.
- Debug traces should contain compact period intent, resolved bounds, row counts, and validation outcomes, not raw workout content.

## Testing Plan

Unit tests:

- period selector resolution around week/month boundaries
- timezone handling
- owner-scoped period repository query
- aggregation totals and null handling
- missing-data facts
- no-workouts behavior
- fake LLM period prose operation

Workflow tests:

- natural language routes to period analysis
- response uses configured language
- no live OpenAI calls
- no other user's workouts in facts
- model unavailable fallback

Visualization tests:

- manifest includes only period datasets and safe column stats
- chart specs compile for bucketed distance/duration/count
- unsupported metric returns typed error
- rendered PNG artifact is produced for a fake period request

Regression tests:

- raw point rows are not present in model inputs
- existing single-workout visualization still works
- existing workout chat still resolves active/latest workouts correctly

## Implementation Notes

Recommended new files:

```text
workout/periods.py
workflows/period_analysis.py
tests/test_periods.py
tests/test_period_analysis_workflow.py
```

Likely existing files to extend:

```text
core/routing.py
core/i18n.py
llm/gateway.py
llm/operations.py
storage/repositories.py
storage/unit_of_work.py
visualization/datasets.py
visualization/specs.py
workflows/visualization.py
tests/test_visualization_workflow.py
docs/LLM_CONTRACTS.md
docs/VISUALIZATION_SPEC.md
docs/WORKOUT_SPEC.md
docs/COMMAND_SPEC.md
```

Keep changes staged by capability. Do not mix prose MVP, visualization, comparison, and slash-command work into one large change unless the implementation is already small.

## Open Decisions

- Should current week/month include only elapsed time or the full calendar period?
- Should week start be configurable or fixed to Monday?
- Should period analysis be a new workflow or a mode of workout chat?
- Should slash commands be added in MVP or after natural-language behavior works?
- Should HR-zone period aggregation require point reads in MVP, or wait until visual period datasets exist?
- What maximum period length should be allowed for interactive requests?
