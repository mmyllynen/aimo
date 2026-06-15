# Aimo Rewrite Plan

## Intent

Aimo is a Discord-native personal training assistant. It should feel like one coherent bot that can:

- answer normal conversational messages in the configured language
- understand workout-related questions and answer as a concise, credible coach
- ingest GPX attachments from Discord and store them as user-owned workout records
- maintain lightweight user profile data, including heart-rate zones
- keep channel history and summaries so follow-up messages work naturally
- list, inspect, activate, delete, and reference saved workouts
- create workout visualizations from natural-language requests and return image files
- expose debug information to the requesting/admin user without leaking internal state to channels

The product intent is not "an LLM with arbitrary tools". The product intent is a dependable Discord bot with a small set of predictable user workflows. The language model is useful for language understanding, planning, and wording, but the application should own state transitions, data limits, validation, rendering, and error handling.

## Problems To Avoid

The architecture should avoid these failure modes:

- Routing, data selection, visualization spec writing, and response generation are too tightly coupled to live model/tool loops.
- Large tool outputs can accidentally become model input in later steps.
- Clarification behavior is inconsistent because the model is allowed to ask even when the workflow is already determined.
- Some behavior relies on prompt discipline instead of explicit workflow contracts.
- Visualization has too much freedom at the wrong layer: the model can describe charts, but Python must deterministically decide what data exists and how it is bound.
- Runtime storage is JSON-file based and scattered by concern, which is workable for a prototype but weak for transactional updates, queries, and schema evolution.
- Debugging exists, but operational observability should be designed as a first-class system rather than a best-effort trace dump.

The implementation should preserve the product intent in `PRODUCT_SPEC.md`.

## Design Principles

1. Deterministic workflows first, model calls second.
2. LLM output must be structured, bounded, validated, and never directly trusted.
3. Each workflow has an explicit state machine with clear terminal states: success, clarify, user error, system error.
4. Tools and data providers return bounded summaries by default; raw series data is passed only to deterministic code, not through routing models.
5. The app chooses allowed actions from workflow context. The model may classify and fill structured slots, but it does not decide arbitrary control flow.
6. Discord UX should be concise and practical: public answers for mentions, ephemeral responses for slash/admin/debug where appropriate.
7. All persistent data has ownership, retention, and schema versioning.
8. Visualization is a compiled artifact pipeline: request -> visualization intent -> resolved dataset -> validated visualization spec -> rendered image.
9. Failures should be specific and recoverable. The bot should say what it can do next, not leak internal implementation errors.

## Proposed High-Level Architecture

### 1. Discord Adapter

Responsibilities:

- receive messages, mentions, slash commands, and attachments
- normalize inbound events into internal command objects
- update user `last_seen` metadata
- write inbound events to history
- send text replies, files, ephemeral messages, and debug artifacts
- apply Discord-specific safety such as disabled broad mentions

This layer should contain no domain interpretation beyond "what Discord event arrived".

### 2. Application Router

Responsibilities:

- convert normalized events into one of a small set of application workflows
- invoke a lightweight intent classifier only when needed
- enforce domain policy and feature availability
- route to workflow handlers

Routing output should be a small object:

```text
workflow: chat | workout_chat | workout_ingest | workout_management | visualization | debug | help
confidence: high | medium | low
slots: bounded structured fields
clarification: optional
```

The router should not fetch raw workouts, raw GPX points, or visualization datasets. It may fetch compact counts or recent workout summaries if needed.

### 3. Workflow Layer

Each workflow is a deterministic state machine.

Core workflows:

- `ChatWorkflow`
- `WorkoutChatWorkflow`
- `GpxIngestWorkflow`
- `WorkoutManagementWorkflow`
- `VisualizationWorkflow`
- `DebugWorkflow`
- `HelpWorkflow`

Each workflow receives:

- normalized request
- authenticated user context
- channel context
- feature policy
- repositories/services it is allowed to call

Each workflow returns:

- reply text, file, or ephemeral payload
- state updates
- history/debug events
- user-facing error if needed

### 4. Domain Services

Domain services are pure application services, not Discord-aware and not LLM-aware unless explicitly named.

Recommended services:

- `UserProfileService`: identity, last seen, HR zones, user preferences
- `HistoryService`: append events, read recent turns, maintain summaries
- `WorkoutLibraryService`: list, retrieve, activate, delete, filter workouts
- `GpxIngestService`: validate attachment, parse GPX, derive canonical workout record
- `WorkoutAnalysisService`: metrics, splits, HR zones, streams, derived summaries
- `VisualizationService`: resolve visualization request, build datasets, validate spec, render image
- `DebugTraceService`: structured traces and admin/debug exports

### 5. LLM Gateway

The LLM gateway should expose only a few narrow operations:

- `classify_intent(request_summary) -> structured intent`
- `extract_workout_reference(text, candidates) -> structured selection`
- `write_visualization_spec(intent, dataset_manifest) -> visualization spec`
- `write_chat_reply(context, facts) -> text`
- `write_workout_reply(context, facts) -> text`
- `summarize_history(turns) -> summary`

The gateway should enforce:

- model selection per operation
- token budgets
- JSON schema validation
- timeout and retry policy
- output redaction where needed
- no unbounded tool loops in routing

LLM calls should be observable as spans, but workflow correctness should not depend on free-form prompt behavior.

## Data Architecture

Use a single persistent store with explicit schema versions. SQLite is sufficient and simpler than a collection of JSON files.

Suggested tables:

- `users`
- `user_profiles`
- `heart_rate_zones`
- `guild_policies`
- `channels`
- `history_events`
- `channel_summaries`
- `workouts`
- `workout_streams`
- `workout_points`
- `workout_tags`
- `active_workouts`
- `attachments`
- `debug_traces`
- `rendered_artifacts`

Store raw GPX files as files or blobs keyed by immutable attachment/workout id. Store parsed metadata and streams in queryable tables.

Rules:

- Every workout belongs to one Discord user.
- Every workout records source guild/channel/message where available.
- Every stored schema has a `schema_version`.
- Raw GPX is immutable after ingest.
- Derived data can be regenerated and versioned.
- Large point streams are never embedded into model prompts.

## Core Workflows

### Mention Chat

1. Discord adapter receives mention.
2. Inbound event is persisted.
3. Router classifies workflow.
4. Chat workflow loads bounded history/profile facts.
5. LLM writes concise final reply.
6. Reply is sent and persisted.
7. Summary refresh is scheduled or run with bounded input.

### Workout Conversation

1. Router identifies workout conversation.
2. Workflow resolves explicit references such as active workout, latest workout, date, tag, or numbered list item.
3. Domain service provides compact facts.
4. LLM writes a coach-style response based only on supplied facts.
5. If data is unavailable, workflow decides whether to answer generally or ask a specific clarification.

### GPX Ingest

1. Attachment is downloaded with size/type limits.
2. GPX parser validates XML and extracts track/route content.
3. Canonical workout builder derives metrics, streams, tags, and summary.
4. Duplicate detection uses content hash.
5. Workout is stored transactionally.
6. Active workout is updated if appropriate.
7. Bot replies with a compact ingest summary.

This workflow should not require an LLM.

### Workout Management Slash Commands

Commands should be deterministic:

- list workouts
- show workout details
- set active workout
- delete workout
- configure HR zones
- show help

LLM should not be involved unless the command explicitly asks for natural-language interpretation.

### Visualization

Visualization should be a multi-stage deterministic pipeline.

1. Router selects `visualization`.
2. Visualization workflow extracts structured request slots:
   - workout selection: latest, active, explicit id, date, range, tag
   - chart goal: time series, comparison, distribution, summary
   - metrics: heart rate, pace, elevation, distance, duration, HR zones
   - transforms: normalize, smooth, aggregate, compare
3. Workout resolver returns a bounded candidate set.
4. Dataset builder constructs a manifest:
   - available datasets
   - column ids
   - row counts
   - units
   - missing metrics
   - allowed transforms
5. LLM may propose a `VisualizationSpec` using only the manifest, not raw points.
6. Python validates and compiles the spec.
7. Python fetches raw series data internally and applies transforms.
8. Renderer creates the image.
9. Bot sends image plus short caption.

Important rule: clarification is a workflow decision. If the user explicitly says "latest workout", missing metrics should result in a best-effort chart plus a note, or a precise "latest workout has no HR data" message. It should not ask whether the user meant latest or a specific workout.

## Visualization Contract

Use two separate specs:

### Visualization Intent

Produced from the user request. Small and semantic.

```text
workout_selector
x_metric
requested_metrics
transform_hints
comparison_mode
notes_requested
```

### Visualization Spec

Produced after data is resolved. Fully deterministic and validated.

```text
datasets
marks
encodings
transforms
filters
aggregation
scales
annotations
layout
output
```

The LLM can help propose the visualization spec, but it only sees a dataset manifest. Python owns the final compilation, alias resolution, unit handling, transform application, and render validation.

## Clarification Policy

Clarify only when the workflow cannot proceed safely.

Do not clarify when:

- the user says latest workout
- the user says active workout
- there is exactly one plausible candidate
- a best-effort result can be produced with a clear note

Clarify when:

- several candidates match equally and the requested comparison depends on which one is chosen
- the requested operation would be misleading without user choice
- required private/admin action lacks authorization
- the command is destructive and confirmation is required

Clarification text should name the missing decision, not ask broad generic questions.

## Reliability Model

### Bounded Model Inputs

- Routing input: request text, compact state, maybe recent summary.
- Workout selection input: small candidate list only.
- Visualization planning input: dataset manifest only.
- Reply writing input: facts and selected context only.

No raw GPX, no full history dumps, no large point arrays in model calls.

### Validation Gates

Every model output goes through:

- JSON/schema validation
- enum normalization
- ownership checks
- workflow state validation
- data availability checks
- output-size limits

### Error Handling

User-visible errors should be categorized:

- unsupported attachment
- no matching workout
- data missing for requested metric
- visualization plan invalid
- renderer failed
- temporary model/API failure
- permission denied

Each category should have a stable localized response template.

### Observability

Every request should create a trace:

- inbound event id
- workflow
- routing decision
- model calls and token usage
- data queries and row counts
- selected workouts
- generated artifact ids
- final user-visible action
- failure category if any

`/debug` should expose this trace as structured JSON, with large payloads summarized and sensitive values redacted.

## Testing Strategy

Test at four levels:

1. Pure domain tests:
   - GPX parsing
   - workout metric derivation
   - HR zone derivation
   - workout selection
   - chart transforms
   - visualization spec validation

2. Workflow tests:
   - latest workout visualization does not clarify
   - missing metric produces a useful note or data-missing response
   - GPX ingest stores duplicate only once
   - slash workout commands mutate only intended records

3. Contract tests:
   - model schemas reject malformed output
   - route classifier cannot access large data providers
   - visualization planner receives manifest, not raw points

4. End-to-end tests:
   - mention chat
   - mention workout question
   - GPX upload
   - list/set/delete workout
   - create visualization image
   - `/debug`

Use fake LLM clients for deterministic tests. Do not make normal tests depend on live OpenAI responses.

## Suggested Rewrite Phases

### Phase 1: Foundations

- Define canonical request/event model.
- Define workflow result model.
- Choose SQLite schema and migration strategy.
- Implement repositories and transaction helpers.
- Implement trace/event logging.

### Phase 2: Discord Shell

- Build Discord adapter around the canonical event model.
- Implement deterministic slash commands for help, debug, and workout management.
- Keep responses safe with disabled broad mentions and consistent file handling.

### Phase 3: Data Layer

- Implement GPX ingest service.
- Store raw GPX and canonical workout records.
- Implement workout listing, filtering, active selection, and HR zone config.
- Import documented exported data if needed.

### Phase 4: LLM Gateway

- Implement narrow model operations with schemas.
- Add token budgets, retries, timeouts, logging, and response validation.
- Prohibit large-data access from routing/classification operations.

### Phase 5: Chat And Workout Workflows

- Implement chat workflow using bounded history/profile context.
- Implement workout conversation workflow using resolved facts.
- Add deterministic clarification policy.

### Phase 6: Visualization Pipeline

- Implement visualization intent extraction.
- Implement workout and dataset resolution.
- Implement dataset manifest generation.
- Implement visualization spec compilation and validation.
- Implement renderer and image delivery.

### Phase 7: Hardening

- Add full regression suite.
- Add load/size tests for long histories and long GPX tracks.
- Add operational debug views.
- Add recovery behavior for model/API outages.
- Run shadow checks against v3 acceptance cases before switching production.

## Success Criteria

The rewrite is successful when:

- A user can upload GPX files and reliably see stored workouts.
- A user can ask natural-language workout questions and get concise, data-grounded answers.
- A user can ask for "latest workout" visualizations without unnecessary clarification.
- Visualization never fails because routing saw too much raw data.
- Missing data is reported clearly and specifically.
- All model calls are bounded, observable, and schema-validated.
- Runtime state is queryable and migration-friendly.
- Debug output explains what happened without exposing secrets or huge payloads.
- The codebase has one obvious path for each workflow.

## Non-Goals For The Rewrite

- Building a full training-plan platform.
- Letting the model write arbitrary persistent data.
- Exposing raw filesystem paths or storage internals to model prompts.
- Supporting every possible chart type before the core visualization pipeline is dependable.
- Recreating the current module layout for familiarity.

## Recommended Shape

The final system should look like this conceptually:

```text
Discord Adapter
  -> Application Router
      -> Workflow State Machine
          -> Domain Services
              -> Repositories
              -> LLM Gateway
              -> Renderer
          -> Response Builder
  -> Discord Reply/File Sender
```

This keeps the bot flexible where language understanding matters, and strict where correctness matters.
