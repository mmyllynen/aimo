# Aimo Roadmap

## Purpose

This roadmap tracks Aimo from the original foundation skeleton to a production-capable bot that satisfies the product specifications. The current implementation is already well past the foundation phases; `HANDOVER.md` is the fast current-state entrypoint.

Feature parity means parity with `PRODUCT_SPEC.md`, `COMMAND_SPEC.md`, `WORKOUT_SPEC.md`, `VISUALIZATION_SPEC.md`, `LLM_CONTRACTS.md`, and `OPERATIONS_SPEC.md`.

## Current State

Approximate feature parity is 80%. The current tree is the clean v3 implementation. Do not use `legacy/` or old archived material as implementation guidance.

Current project state contains:

- rewrite plan
- foundation specification
- internationalization specification
- canonical event contracts
- routing target contracts
- workflow result contracts
- error category contracts
- trace event contracts
- internationalization contracts and initial catalogs
- config/runtime bootstrap contracts
- initial SQLite schema draft
- unit tests for internationalization and config/runtime bootstrap
- unit tests for core contracts and import hygiene
- minimal SQLite helper with schema loading and transaction boundary tests
- repositories for users, HR zones, channels, history events, attachments, workouts, active workouts, workout streams/points, debug traces, and rendered artifacts
- repository bundle and unit-of-work wrapper
- Discord adapter shell for snapshot normalization and outgoing payload rendering
- dispatcher foundation that persists inbound user/channel/history data and routes deterministic help/debug/noop workflows
- deterministic `/treenit` workflow support for list/show/active/set-active/delete/HR-zone actions against repositories
- bounded dispatch debug traces with requester/admin access policy
- centralized trace payload redaction and count-based trace pruning
- LLM gateway foundation with typed operations, fake client tests, schema validation, language instruction, raw payload guards, trace events, and an OpenAI Responses API adapter
- chat workflow foundation for mentioned chat through the typed LLM gateway with assistant reply history writes
- GPX ingest foundation with parser, derived workout records, point/stream storage, active workout update, and duplicate detection
- shared workout reference resolver with latest/active/id/list-index/date/title-kind-tag matching and deterministic no-match/ambiguity outcomes
- visualization foundation with shared workout reference resolution, metric aliases, normalized secondary series, dataset request/resolver/manifest, visualization spec compiler/validator, renderer adapter, current line/HR-zone behavior, and missing-metric errors
- workout chat foundation with shared workout reference resolution, bounded workout facts, stream manifests, and persisted assistant replies
- OpenAI Responses API compatible LLM client adapter with fake HTTP tests and no SDK dependency
- application runtime context wiring config, SQLite schema, dispatcher, admin policy, and optional LLM gateway without starting Discord
- Discord attachment download boundary with GPX type/size checks and no `discord.py` dependency
- raw GPX and rendered visualization artifact file writes under configured storage roots with traversal protection
- SQLite migration runner using current schema as version 1 plus numbered migration directory support
- bounded LLM model-call trace events in dispatch debug traces without prompts or model input payloads
- Discord runtime skeleton for message handling, outgoing sends, attachment hydration, and `--run-discord` startup
- Discord slash command specs and registration skeleton for `/aimo`, `/treenit`, and `/debug`, with interaction option and attachment extraction tests
- visualization spec compiler and validation for datasets, metrics, transforms, encodings, marks, and required values
- LLM intent classification routing for mentions and `/aimo syote` with bounded inputs and deterministic fallback
- observability/debug hardening with bounded trace stages for inbound events, repository persistence, routing, workflow execution, LLM calls, visualization rendering, outbound responses, and final results
- `/debug` export limits for large traces with event-count summaries and redacted payloads
- one-way documented JSON data importer with dry-run/apply modes, ownership validation, migration report counts, chat summaries, workout index, active workout, and raw GPX reference import support
- production preflight checks and cutover smoke-test documentation

Current project state does not contain:

- production cutover execution with real local credentials
- every final workflow enhancement, such as chat follow-up summaries and GPX-derived splits
- completed production rollout

## Feature Parity Definition

Aimo is feature-complete when it can:

- run as the Aimo Discord bot
- respond to public mentions
- handle `/aimo`, `/treenit`, and `/debug`
- ingest GPX attachments
- store and manage user-owned workouts
- keep active workout state
- store user profile metadata and HR zones
- store channel history and summaries
- answer normal chat messages in the configured language
- answer workout questions as a concise coach
- generate workout visualizations from natural-language requests
- send rendered image files to Discord
- avoid unnecessary clarification when the user has specified latest/active/specific workout
- expose structured debug traces
- keep model inputs bounded and validated
- survive common API, storage, and data errors with clear user-facing responses

## Phase 1: Foundation Hardening

Goal: make the current skeleton testable and stable.

Tasks:

- Add `tests/`. Done.
- Add tests for canonical event models. Done.
- Add tests for route decision models. Done.
- Add tests for workflow result models. Done.
- Add tests for error and trace models. Done.
- Add schema load test using in-memory SQLite. Done.
- Add import hygiene test for package boundaries. Done.
- Add a minimal `storage` helper that opens SQLite, applies `schema.sql`, and exposes transactions. Done.

Exit criteria:

- All foundation tests pass. Done.
- `schema.sql` loads cleanly. Done.
- Package boundary tests pass. Done.

Not in this phase:

- Discord integration
- LLM calls
- GPX parsing
- visualization rendering

## Phase 2: Storage And Repositories

Goal: build a reliable persistence layer before adding behavior.

Tasks:

- Implement migration runner. Done in skeleton.
- Split initial schema into numbered migrations if needed.
- Implement repositories:
  - users. Done.
  - profiles and HR zones. HR zones done.
  - channels and summaries. Channels done.
  - history events. Done.
  - attachments. Done.
  - workouts. Done.
  - workout points and streams. Done.
  - active workouts. Done.
  - debug traces. Done.
  - rendered artifacts. Done.
- Add transaction boundaries for multi-step updates.
- Add repository tests with temporary SQLite databases. Done.

Exit criteria:

- Repositories cover all data needed for feature parity.
- Inserts, updates, deletes, and queries are tested.
- Workout ownership is enforced at repository/service boundaries.
- Schema supports query patterns needed by later phases.

Not in this phase:

- Discord event handling
- model calls
- GPX derivation logic

## Phase 3: Discord Adapter Shell

Goal: normalize Discord events without domain behavior.

Tasks:

- Implement message/mention normalization into `CanonicalEvent`. Done in shell.
- Implement slash command normalization into `CanonicalEvent`. Done in shell.
- Implement attachment reference normalization. Done in shell.
- Implement outgoing message/file sender abstraction. Done in shell.
- Implement broad mention safety. Done in shell.
- Implement slash command registration. Done in skeleton.
- Implement basic help response wiring in isolation. Done in shell.
- Add adapter tests using fake Discord objects. Done.

Exit criteria:

- Discord-like fake events convert into canonical events. Done.
- Outgoing text/file/ephemeral payloads can be sent through adapter interfaces. Done.
- No workflow contains Discord.py objects. Done.

Not in this phase:

- full bot startup
- actual domain workflows
- LLM integration

## Phase 4: Deterministic Slash Workflows

Goal: implement the slash command features that do not need the LLM.

Tasks:

- Implement `HelpWorkflow`.
- Implement `DebugWorkflow` against the trace repository.
- Implement `WorkoutManagementWorkflow` commands:
  - list workouts. Done in skeleton.
  - show workout. Done in skeleton.
  - set active workout. Done in skeleton.
  - delete workout with confirmation or safe command semantics. Done in skeleton without confirmation UI.
  - set/show HR zones. Done in skeleton.
- Add user/profile touch behavior for slash events.
- Add tests for each slash workflow.

Exit criteria:

- Slash workflows work through canonical events and workflow results.
- All slash outputs are deterministic.
- Debug payloads are structured and bounded.
- Permission checks for debug/admin data are tested.

Not in this phase:

- natural-language chat
- GPX parsing
- visualizations

## Phase 5: GPX Ingest And Workout Library

Goal: make workout data real and reliable.

Tasks:

- Implement attachment download boundary with size/type checks. Done in skeleton.
- Implement GPX parser service or port parser logic into v3 cleanly. Done in skeleton.
- Build canonical workout record derivation:
  - kind/activity/route detection. Done in skeleton.
  - distance. Done in skeleton.
  - duration. Done in skeleton.
  - pace. Done in skeleton.
  - elevation. Done in skeleton.
  - HR and cadence streams. Done in skeleton.
  - splits
  - HR zones
  - tags and summary metadata
- Implement duplicate detection by hash. Done in skeleton.
- Store raw GPX and derived records transactionally. Done in skeleton.
- Implement active workout update policy. Done in skeleton.
- Add ingest workflow tests for activity GPX, route GPX, invalid GPX, duplicate GPX, HR data, and missing timestamps. Activity, invalid, duplicate, and HR done in skeleton.

Exit criteria:

- Users can upload GPX and get a stable ingest summary.
- Workout records can be listed and retrieved from repositories.
- Duplicate uploads do not create duplicate workouts.
- HR zones are applied to derived data when available.

Not in this phase:

- LLM-generated coaching responses
- chart rendering

## Phase 6: LLM Gateway

Goal: add bounded model operations as a controlled infrastructure service.

Tasks:

- Implement typed LLM operation interface. Done in skeleton.
- Add operation-specific schemas:
  - intent classification
  - workout reference extraction
  - chat reply writing
  - workout reply writing
  - visualization intent extraction
  - visualization plan writing
  - history summarization
- Add token budgets per operation.
- Add timeout/retry policy.
- Add HTTP client adapter behind the interface. Done in skeleton.
- Add model-call trace events. Done in skeleton.
- Add tests with fake LLM responses. Done in skeleton.
- Add schema rejection tests. Done in skeleton.
- Add guard ensuring routing/classification cannot receive large workout point data. Done in skeleton.
- Use intent classification for natural-language routing. Done in skeleton for mentions and `/aimo syote`.

Exit criteria:

- All LLM operations are schema-bounded or explicitly text-bounded.
- Fake LLM tests cover success, malformed output, timeout, and unavailable model.
- No workflow uses raw client calls directly.

Not in this phase:

- full chat workflow
- full visualization workflow

## Phase 7: Chat Workflow

Goal: restore normal conversational mention behavior.

Tasks:

- Implement chat routing to `ChatWorkflow`. Done in skeleton.
- Load bounded profile, channel summary, and recent turns. Recent turns done in skeleton.
- Generate concise replies in the configured language through LLM gateway. Done in skeleton.
- Persist inbound and outbound history. Done in skeleton.
- Refresh summaries with bounded input.
- Add follow-up context handling.
- Add tests for normal chat, short follow-ups, summary refresh, and model failure. Normal chat and model failure done in skeleton.

Exit criteria:

- Mention chat works without workout data.
- Replies are concise and Discord-native.
- History and summaries update correctly.
- Model failure produces a stable user-facing response.

Not in this phase:

- workout coaching
- visualization

## Phase 8: Workout Chat Workflow

Goal: restore workout-related conversation with data grounding.

Tasks:

- Route workout questions to `WorkoutChatWorkflow`. Done in skeleton.
- Resolve references:
  - active workout. Done in skeleton.
  - latest workout. Done in skeleton.
  - date. Done in skeleton.
  - tag/type. Done in skeleton.
  - numbered list item. Done in skeleton.
  - explicit id/reference. Done in skeleton.
- Provide bounded workout facts to the LLM. Done in skeleton.
- Answer as a concise coach. Done through LLM operation skeleton.
- Ask clarification only when required by policy.
- Add tests for active/latest workout, missing data, ambiguous references, and general training advice without data. Active/latest/missing data/ambiguous references done in skeleton.

Exit criteria:

- Workout replies are grounded when data exists.
- No workout details are invented.
- Clarification policy is deterministic.
- Follow-ups can stay in workout context.

Not in this phase:

- chart rendering

## Phase 9: Generic Visualization Pipeline

Goal: rebuild visualization as a generic compiled artifact pipeline:

```text
user text
-> visualization intent
-> dataset request
-> dataset resolver
-> dataset manifest
-> visualization spec
-> spec validator/compiler
-> renderer adapter
-> image artifact
```

The target is a generic visualizer, not a growing list of hard-coded chart workflows. Python owns dataset resolution, alias resolution, manifest building, validation, transform execution, and rendering. The LLM may interpret language and propose a bounded visualization spec, but it must not see raw point rows and must not be trusted as the final validator.

Current behavior:

- latest/active/id/date/tag/list-index workout references resolve through the shared resolver
- line chart rendering works for point-series requests through the generic spec path
- HR-zone distribution rendering works through the generic spec path
- metric aliases, normalization, `filter_non_null`, rolling-average smoothing, `aggregate_sum`/`aggregate_avg`, missing-primary-metric errors, artifact storage, and Discord file response boundary exist
- dataset manifests expose a row-free model view with schema, safe stats, null counts, and allowed transforms only
- workout summary metrics can resolve through a reusable `workout_summary` dataset and render through the generic bar-mark path
- recent workout comparison metrics can resolve through a reusable owner-scoped `workout_comparison` dataset and render through the generic bar-mark path

Phase 9 is complete for the current roadmap scope. Future visualization work should still add behavior through reusable datasets, manifests, specs, transforms, encodings, or renderer primitives instead of workflow-specific chart branches.

Tasks:

- Define `DatasetRequest`:
  - source type, such as workout points, workout summary, HR zones, workout collection
  - owner and workout selector
  - requested metrics/dimensions
  - date range and comparison scope
  - Done in skeleton for point-series, HR-zone distribution, workout summary, and recent comparison requests.
- Implement `DatasetResolver`:
  - resolves user-owned datasets only
  - fetches raw series internally
  - produces bounded in-process datasets for Python rendering
  - produces a compact `DatasetManifest` for planning
  - Done in skeleton for workout point, HR-zone distribution, workout summary, and recent comparison datasets.
- Define `DatasetManifest`:
  - dataset ids
  - available columns and canonical metric ids
  - units, dimensions, row counts, null counts, min/max where safe
  - available grouping dimensions
  - supported transforms for each column type
  - Done in skeleton for current datasets, including a row-free model-facing manifest view.
- Replace the legacy chart-specific planning model with `VisualizationSpec`:
  - datasets
  - marks, such as line, point, bar, area, interval, arc
  - encodings, such as x, y, color, group, size
  - transforms, filters, aggregation, sorting, scaling
  - layout, legend, labels, output filename
  - Done in skeleton for current line and bar marks.
- Implement `VisualizationSpecValidator`:
  - validates every dataset and column against the manifest
  - rejects unsupported mark/encoding/data-shape combinations
  - validates transform compatibility
  - returns precise missing-data or invalid-spec categories
  - Done in skeleton for current datasets and marks.
- Implement renderer adapter:
  - maps validated generic specs to concrete PNG rendering
  - contains chart drawing primitives but no user intent logic
  - existing line chart and HR-zone distribution use this adapter in skeleton.
- Update LLM operation boundaries:
  - intent extraction may identify requested datasets and chart goal
  - spec writing receives only `DatasetManifest`, never raw rows
  - Python compiles/fixes/rejects the spec deterministically
- Add tests:
  - user text produces a dataset request for latest workout HR/pace/elevation
  - dataset resolver produces manifest without raw rows for model input. Done for current dataset manifests.
  - spec validator rejects invented columns
  - existing line chart request renders through generic spec path
  - existing HR-zone distribution renders through generic spec path
  - recent workout comparison renders through generic spec path
  - missing primary metric still returns a precise error
  - no unnecessary clarification for latest/active/specific workout

Exit criteria:

- Natural-language visualization requests return image files through the generic spec pipeline.
- No new visualization feature requires a workflow-specific chart branch.
- Large raw point data never enters routing or planning model input.
- Missing metrics produce a precise note or error.
- Rendered images pass basic non-empty validation.

Not in this phase:

- every possible chart type
- interactive charts
- model-visible raw datasets

## Phase 10: Observability And Debug

Goal: make failures explainable.

Tasks:

- Finalize trace schema and payload redaction. Done.
- Add trace spans for:
  - inbound event. Done.
  - routing. Done.
  - workflow stages. Done.
  - repository calls. Done as bounded repository-stage summaries.
  - LLM calls. Done.
  - render calls. Done for visualization render outcomes.
  - outbound response. Done.
- Implement `/debug` export from v3 trace store. Done.
- Add payload-size limits and summaries for large traces. Done.
- Add tests for debug visibility and redaction. Done.

Exit criteria:

- Every request has a trace. Done.
- `/debug` returns the latest relevant trace. Done.
- Large payloads and secrets are not exposed. Done.

Not in this phase:

- production switch

## Phase 11: Data Import And Migration

Goal: support importing previously exported user/runtime data into storage through documented import formats.

Tasks:

- Write one-way import readers for documented export formats. Done for `aimo.v3.import.v1` JSON in `docs/DATA_IMPORT_SPEC.md`.
- Migrate:
  - user profiles. Done.
  - HR zones. Done.
  - history events. Done.
  - chat summaries. Done.
  - workout index. Done.
  - active workouts. Done.
  - raw GPX references. Done as metadata references without mutating files.
- Validate ownership and counts. Done.
- Produce migration report. Done.
- Add dry-run mode. Done.
- Add tests with fixture data. Done.

Exit criteria:

- Migration can run in dry-run and apply modes. Done.
- Counts and key records match expectations. Done.
- Imported raw GPX files remain intact. Done.

Not in this phase:

- deleting source data

## Phase 12: Shadow Run

Goal: compare v3 behavior without replacing production.

Tasks:

- Add a shadow runner that receives copied canonical events.
- Run v3 workflows without sending public replies.
- Store shadow results and traces.
- Compare:
  - route decisions
  - clarification decisions
  - selected workouts
  - visualization plans
  - error categories
- Add operational review checklist.

Exit criteria:

- Aimo handles representative real events without crashes.
- Known problem cases are fixed.
- Shadow traces are reviewable.

Not in this phase:

- production cutover

## Phase 13: Production Cutover

Goal: switch Aimo to the new runtime safely.

Tasks:

- Add runtime enablement flag.
- Add production preflight checks. Done in skeleton.
- Add manual smoke-test checklist. Done in skeleton.
- Run final migration.
- Start the new bot path.
- Verify:
  - login
  - slash command sync
  - mention chat
  - GPX ingest
  - workout list
  - visualization
  - debug
- Monitor logs and traces.

Exit criteria:

- Aimo serves production traffic.
- Critical feature parity checks pass.
- Restore-from-backup path is known and documented.

## Cross-Cutting Requirements

### Security And Privacy

- Do not expose tokens or raw secrets in traces.
- Do not leak one user's workouts to another user.
- Use explicit owner checks for every workout query.
- Disable broad Discord mentions by default.

### Bounded Data

- Routing sees no raw GPX or workout points.
- LLM planning sees manifests, not large series.
- Replies see facts, not storage internals.
- Debug export summarizes large payloads.

### Deterministic Clarification

Clarification is allowed only when the workflow cannot proceed safely. Explicit latest/active/specific workout requests must not trigger "which workout?" questions.

### Test Discipline

- Fake LLMs for normal tests.
- Temporary SQLite databases for repository tests.
- No live Discord tests in unit suite.
- Image render tests should verify non-empty image output.

## Risk Register

### Discord Adapter Risk

Risk: Discord-specific objects leak into workflows.

Mitigation: adapter-only conversion to canonical events; tests use fake Discord objects.

### Storage Risk

Risk: migration corrupts or loses workout data.

Mitigation: dry-run migration, count validation, raw GPX immutability, backup before apply.

### LLM Risk

Risk: model returns malformed or over-broad output.

Mitigation: narrow operations, schemas, strict validation, deterministic fallback categories.

### GPX Risk

Risk: different GPX producers encode HR/cadence/routes inconsistently.

Mitigation: fixture suite with multiple GPX shapes; canonical stream model; missing-data handling.

### Visualization Risk

Risk: chart requests fail because model invents columns or chooses impossible data.

Mitigation: manifest-only planning, compile-time validation, alias resolution, deterministic missing metric responses.

### Operational Risk

Risk: production switch hides failures until users report them.

Mitigation: shadow run, structured traces, explicit rollout checklist, rollback flag.

## Recommended Immediate Next Task

Phase 11 data import and migration is complete for the current roadmap scope. Continue production cutover execution prep or move to Phase 12 shadow run.

High-value next steps:

- add production host restart/deployment docs and run the real Discord smoke test when credentials are available
- add chat follow-up context and summary refresh
- add GPX-derived features such as splits, HR-zone enrichment at ingest time, and better workout tags

Acceptance for the next completed step:

- `python3 -m unittest discover` passes
- no live model calls in tests
- LLM inputs stay bounded and schema-validated
- raw workout points stay out of LLM inputs
- runtime bootstrap remains integration-free
- no visualization feature is implemented as a workflow-specific chart branch
