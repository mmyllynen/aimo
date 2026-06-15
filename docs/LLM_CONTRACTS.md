# Aimo v3 LLM Contracts

## Purpose

LLM use in v3 is limited to narrow operations. Workflows own control flow, validation, data access, and error handling.

## Global Rules

- Every structured operation has a schema.
- Every operation has a token budget.
- Large raw workout point arrays are never model input.
- Routing/classification cannot access data providers that return large payloads.
- Model output is advisory until validated.
- Invalid output maps to a typed application error or deterministic fallback.

## Operation: Intent Classification

Input:

- event kind
- user text
- whether attachments exist
- compact channel state
- optional recent summary

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

## Operation: Workout Reference Extraction

Input:

- user text
- compact candidate workouts
- active workout summary if any

Output:

```text
selector_type
selector_value
matched_workout_ids
ambiguity_reason
requires_clarification
```

Rules:

- exact id wins
- latest and active are explicit selectors
- do not reinterpret latest as ambiguous

## Operation: Chat Reply

Input:

- user text
- bounded recent context
- channel summary
- profile facts
- optional workflow facts

Output:

```text
reply_text
tone
should_update_summary
```

Rules:

- the configured bot language from `aimo.conf`
- concise
- no internal implementation details
- no broad mentions

## Operation: Workout Reply

Input:

- user text
- resolved workout facts
- missing data facts
- profile facts such as HR zones
- bounded recent context

Output:

```text
reply_text
claims_used
missing_data_notes
```

Rules:

- do not invent workout facts
- use coach-like tone
- keep reply concise

## Operation: Visualization Intent Extraction

Input:

- user text
- compact routing context

Output:

```text
workout_selector
requested_datasets
requested_metrics
grouping_hints
transform_hints
date_range
comparison_mode
```

Rules:

- semantic intent only
- no dataset rows
- canonical metric aliases preferred when possible
- not the final render instruction

## Operation: Visualization Spec Writing

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

- may reference only manifest columns
- must not invent columns
- must represent missing metrics explicitly
- Python validates and compiles the spec before rendering

## Operation: History Summarization

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
- avoid storing secrets
- keep summary short

## Error Mapping

LLM operation errors map to:

- malformed structured output -> `model_unavailable` or workflow-specific fallback
- timeout -> `model_unavailable`
- context budget exceeded -> implementation error; must be prevented by input bounding
- safety refusal -> user-facing inability response when relevant
