# Aimo LLM Contracts

LLM use is limited to narrow typed operations. Workflows own control flow, validation, data access, permissions, rendering, and state changes.

## Global Rules

- Every structured operation has a schema, timeout, and token budget.
- Inputs are bounded before the call.
- Raw GPX, full workout point arrays, image bytes, secrets, stack traces, and unrelated history are forbidden inputs.
- Model output is advisory until parsed and validated.
- Invalid output maps to a typed application error or deterministic fallback.
- User-visible LLM prose must be instructed to use the configured language.
- Plustägit (`+word`), miinustägit (`-word`), and tarkenteet (`key=value`) are formal deterministic controls. Python applies the supported vocabulary after LLM intent extraction.

## Intent Classification

Input: event kind, user text, attachment presence, and compact channel state.

Output:

```text
workflow
confidence
slots
clarification
reason
```

Allowed workflows: `chat`, `workout_chat`, `gpx_ingest`, `workout_management`, `visualization`, `debug`, and `help`.

## GPX Title Extraction

Input: user text and supported GPX attachment count.

Output:

```text
title
```

Rules: return a title only when the user clearly asks to name one uploaded workout, route, or route plan. Finnish examples include `anna sille nimeksi "Aamulenkki"`, `nimeä se "Juhannusreitti"`, and `nimellä "..."`; English examples include `name it "..."`, `call it "..."`, and `give it the name "..."`. Return an empty title for multiple attachments, multiple names, vague descriptions, or inferred titles. Python applies deterministic `nimi="..."` / `name="..."` tarkenteet before this operation and ignores model titles outside single-attachment mention uploads.

## Chat Reply

Input: user text, bounded recent context, optional profile facts, and workflow capability facts.

Output:

```text
reply_text
tone
should_update_summary
```

Rules: keep replies concise, avoid broad mentions/internal details, and do not claim unavailable stored data.

## Workout Reply

Input: user text, resolved workout facts, missing-data facts, profile facts such as selector type or HR zones, and bounded recent context.

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules: use provided facts as ground truth, do not invent workout details, and state missing data plainly.

## Visualization Intent

Input: user text, compact routing context, and optional previous visualization context.

Output:

```text
workout_selector
requested_metrics
transform_hints
date_range
comparison_mode
layout_mode
chart_kind
output_mode
social_style
context_update
```

Rules:

- Return semantic intent only.
- Map user-language metric aliases to canonical ids.
- `chart_kind` is a generic hint: `auto`, `line`, `bar`, `pie`, or `map`.
- `output_mode` defaults to `chart`; use `social_image` only for shareable/social/poster workout images such as Finnish `somekuva`. A normal route-map request such as `näytä reitti kartalla` is `chart_kind=map`, `output_mode=chart`.
- When `compact_routing_context.active_workout` is present and the user asks for `the route`, `this route`, Finnish `reitti`, or `näytä reitti kartalla` without an explicit different selector, prefer `workout_selector.type=active`. Use `latest` only for explicit latest/last/viimeisin/uusin wording.
- For `social_image`, return a single-workout selector, include `route`, and include explicit requested stat metrics when the user asks for them.
- Use previous visualization context only when the user refers to the previous/current/same chart or asks for a refinement.
- Return complete intents, not partial patches.
- `context_update.set_current_workout` may be true only for a concrete single-workout request; Python performs the update after safe owner-scoped resolution and successful execution.

## Visualization Revision

Python may make one bounded revision request when a visualization intent/spec cannot be compiled.

Input: original user text, failed intent/spec metadata, structured validation errors, compact dataset manifest, allowed generic primitives, and optional previous visualization context.

Output: the same complete visualization intent shape as above.

Rules: fix only reported validation failures within allowed primitives; do not invent metrics, columns, datasets, transforms, chart kinds, or metric-specific chart logic.

## Workout Reference Extraction

Input: user text, compact candidate workout facts, and optional current workout facts.

Output:

```text
selector_type
selector_value
matched_workout_ids
ambiguity_reason
requires_clarification
set_current_workout
```

Rules: identify concrete references without raw point data. Python owns owner checks, selector resolution, ambiguity handling, and current-workout updates.

## Period Request Interpretation

Input: user text, current datetime, timezone, allowed scope types, allowed canonical metrics, allowed grouping values, allowed output modes, and compact routing context.

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

- Use `none` when the request is not about a workout set or period.
- Use `single_workout` only when the request belongs to the workout-reference path.
- Use relative scopes such as `current_week`, `last_week`, `current_month`, `last_month`, and `rolling_days` for period requests.
- Python owns date resolution, owner-scoped storage queries, filtering, aggregation, validation, and rendering.

## Period Analysis Reply

Input: user text, compact period facts calculated by Python, missing-data facts, and bounded recent context.

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules: use period facts as ground truth, write concise prose in the configured language, and do not invent workouts, metrics, dates, comparisons, or unavailable data.

## Future: History Summary

Input: bounded recent turns and previous summary.

Output:

```text
summary
retained_facts
discarded_noise_categories
```

Rules: preserve stable context, avoid secrets, and keep summaries short.

## Error Mapping

- malformed structured output -> workflow-specific fallback or `model_unavailable`
- timeout -> `model_unavailable`
- context budget exceeded -> implementation bug; prevent with input bounding
- safety refusal -> concise user-facing inability response when relevant
