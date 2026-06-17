# Aimo LLM Contracts

## Purpose

LLM use is limited to narrow typed operations. Workflows own control flow, validation, data access, permissions, rendering, and state changes.

## Global Rules

- Every structured operation has a schema.
- Every operation has a token budget and timeout.
- Model inputs are bounded before the call.
- Raw GPX and full workout point arrays are never model planning input.
- Model output is advisory until parsed and validated.
- Invalid output maps to a typed application error or deterministic fallback.
- User-visible LLM prose must be instructed to use the configured language.

## Intent Classification

Input:

- event kind
- user text
- attachment presence
- compact channel state

Output:

```text
workflow
confidence
slots
clarification
reason
```

Allowed workflows:

- chat
- workout_chat
- gpx_ingest
- workout_management
- visualization
- debug
- help

Forbidden input:

- raw GPX
- workout point rows
- full channel history
- secrets

## Chat Reply

Input:

- user text
- bounded recent context
- optional profile facts
- workflow capability facts

Output:

```text
reply_text
tone
should_update_summary
```

Rules:

- concise
- no broad mentions
- no internal implementation details
- no claims about unavailable stored data

## Workout Reply

Input:

- user text
- resolved workout facts
- missing data facts
- profile facts such as selector type or HR zones
- bounded recent context

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules:

- do not invent workout facts
- use practical coach-like tone
- state missing data plainly

## Visualization Intent

Input:

- user text
- compact routing context
- optional previous visualization context

Output:

```text
workout_selector
requested_metrics
transform_hints
date_range
comparison_mode
layout_mode
chart_kind
context_update
```

Rules:

- semantic intent only
- no dataset rows
- map user-language metric aliases to canonical ids before returning output
- Python validates and normalizes before repository access
- `chart_kind` is a generic mark hint such as `auto`, `line`, `bar`, or `pie`; it must not encode metric-specific behavior
- previous visualization context may be present even for new requests; use it only when the user refers to the previous/current/same chart or asks for a refinement
- when using previous visualization context, return a complete updated intent rather than a partial patch
- previous visualization context may contain prior intent/spec metadata and selected ids, but never raw rows, raw GPX, or image bytes
- `context_update.set_current_workout` may be true only when the request concretely selects one workout that should become the current workout context; Python performs the update only after safe owner-scoped resolution and successful workflow execution

## Visualization Spec

Input:

- visualization intent
- dataset manifest
- allowed marks
- allowed transforms

Output:

```text
visualization_spec
caption_draft
```

Rules:

- reference only manifest dataset ids and columns
- do not invent columns or metrics
- represent missing metrics explicitly
- Python validates/compiles before rendering
- choose generic marks and transforms from allowed capabilities instead of describing custom chart logic

## Visualization Revision

Input:

- original user text
- failed intent/spec metadata
- structured validation errors
- dataset manifest
- allowed generic primitives
- optional previous visualization context

Output:

```text
workout_selector
requested_metrics
transform_hints
date_range
comparison_mode
layout_mode
chart_kind
context_update
```

Rules:

- one revision attempt per visualization request
- return a complete replacement, not a patch
- fix only the reported validation failures within allowed primitives
- do not invent metrics, columns, datasets, transforms, chart kinds, or metric-specific chart logic
- input must not include raw rows, raw GPX, image bytes, secrets, stack traces, or unrelated history
- Python validates the replacement exactly like the first attempt

## Workout Reference Extraction

Input:

- user text
- compact candidate workout facts
- optional current workout facts

Output:

```text
selector_type
selector_value
matched_workout_ids
ambiguity_reason
requires_clarification
set_current_workout
```

Rules:

- identify concrete workout references without raw point data
- use `matched_workout_ids` when the candidate list clearly identifies the referenced workout
- set `requires_clarification` for ambiguous references
- set `set_current_workout` only when the user is concretely referring to one workout that should become the current workout context
- Python owns owner checks, selector resolution, ambiguity handling, and the actual current-workout update

## Period Request Interpretation

Input:

- user text
- current datetime
- timezone
- allowed scope types
- allowed canonical metrics
- allowed grouping values
- allowed output modes
- compact routing context

Output:

```text
scope_type
scope_value
start_date
end_date
rolling_days
filters
metrics
grouping
output_mode
comparison_mode
reason
```

Rules:

- use `none` when the request is not about a workout set or period
- use `single_workout` only when the request clearly belongs to the existing workout-reference path
- use `all_workouts` for the user's complete stored workout set
- use relative scopes such as `current_week`, `last_week`, `current_month`, `last_month`, and `rolling_days` for period requests
- map user-language metric aliases to canonical ids
- do not calculate totals, resolve ownership, query data, or render output
- Python owns date resolution, owner-scoped storage queries, filtering, aggregation, validation, and rendering
- input must not include raw GPX, raw points, secrets, or unrelated history

## Period Analysis Reply

Input:

- user text
- compact period facts calculated by Python
- bounded recent context

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules:

- write concise prose in the configured language
- use `period_facts` as ground truth
- do not invent workouts, metrics, dates, comparisons, or unavailable data
- mention missing requested metrics when `missing_data_notes` require it

## Future: History Summary

Input:

- bounded recent turns
- previous summary

Output:

```text
summary
retained_facts
discarded_noise_categories
```

Rules:

- preserve stable context
- avoid secrets
- keep summary short

## Error Mapping

- malformed structured output -> workflow-specific fallback or `model_unavailable`
- timeout -> `model_unavailable`
- context budget exceeded -> implementation bug; prevent with input bounding
- safety refusal -> concise user-facing inability response when relevant
