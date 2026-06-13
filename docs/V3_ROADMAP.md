# Aimo Roadmap

## Purpose

This roadmap takes Aimo from the current foundation skeleton to a production-capable bot that satisfies the product specifications.

Feature parity means parity with `PRODUCT_SPEC.md`, `COMMAND_SPEC.md`, `WORKOUT_SPEC.md`, `VISUALIZATION_SPEC.md`, `LLM_CONTRACTS.md`, and `OPERATIONS_SPEC.md`.

## Current State

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
- dispatcher skeleton with deterministic help, debug, and noop workflows
- deterministic `/treenit` workflow skeleton for workout management actions
- bounded dispatch debug traces with requester/admin access policy
- centralized trace payload redaction and count-based trace pruning
- LLM gateway skeleton with typed operations, fake client tests, schema validation, and raw payload guards
- chat workflow skeleton for mentioned chat through the typed LLM gateway with assistant reply history writes
- GPX ingest foundation with parser, derived workout records, point/stream storage, active workout update, and duplicate detection
- visualization foundation with latest/active/id workout resolution, metric aliases, normalized secondary series, PNG line rendering, and missing-metric errors
- workout chat foundation with latest/active/id resolution, bounded workout facts, stream manifests, and persisted assistant replies

Current project state does not contain:

- numbered migration runner
- live Discord runtime binding
- live OpenAI/LLM gateway adapter
- complete workflow handlers
- complete visualization pipeline
- data migration
- production integration

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

- Implement migration runner.
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

- Implement attachment download boundary with size/type checks.
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
- Store raw GPX and derived records transactionally. Derived records done; raw file writing remains outside skeleton.
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
- Add model-call trace events.
- Add tests with fake LLM responses. Done in skeleton.
- Add schema rejection tests. Done in skeleton.
- Add guard ensuring routing/classification cannot receive large workout point data. Done in skeleton.

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
  - date
  - tag/type
  - numbered list item
  - explicit id/reference. Exact id done in skeleton.
- Provide bounded workout facts to the LLM. Done in skeleton.
- Answer as a concise coach. Done through LLM operation skeleton.
- Ask clarification only when required by policy.
- Add tests for active/latest workout, missing data, ambiguous references, and general training advice without data. Active/latest/missing data done in skeleton.

Exit criteria:

- Workout replies are grounded when data exists.
- No workout details are invented.
- Clarification policy is deterministic.
- Follow-ups can stay in workout context.

Not in this phase:

- chart rendering

## Phase 9: Visualization Pipeline

Goal: rebuild visualization as a reliable compiled artifact pipeline.

Tasks:

- Implement visualization intent extraction.
- Implement workout resolver for selectors:
  - latest. Done in skeleton.
  - active. Done in skeleton.
  - explicit id/reference. Exact id done in skeleton.
  - date/range
  - tag/type
- Implement dataset manifest builder.
- Implement render plan compiler and validator.
- Implement metric alias resolution. Done in skeleton.
- Implement transforms:
  - normalize to primary series range. Done in skeleton.
  - smoothing
  - aggregation
  - filtering
- Implement renderer for v1 chart families:
  - line. Done in skeleton.
  - scatter
  - bar
  - area
  - pie
  - histogram
- Add image artifact storage.
- Add Discord file response integration. Done at workflow-result boundary.
- Add tests for:
  - latest workout HR/pace/elevation plot. Done in skeleton.
  - latest workout missing HR. Done in skeleton.
  - HR zone distribution
  - weekly/monthly summary chart
  - invalid render plan
  - no unnecessary clarification for latest/active workout. Latest missing metric done in skeleton.

Exit criteria:

- Natural-language visualization requests return image files.
- Large raw point data never enters routing or planning model input.
- Missing metrics produce a precise note or error.
- Rendered images pass basic non-empty validation.

Not in this phase:

- every possible chart type
- interactive charts

## Phase 10: Observability And Debug

Goal: make failures explainable.

Tasks:

- Finalize trace schema and payload redaction.
- Add trace spans for:
  - inbound event
  - routing
  - workflow stages
  - repository calls
  - LLM calls
  - render calls
  - outbound response
- Implement `/debug` export from v3 trace store.
- Add payload-size limits and summaries for large traces.
- Add tests for debug visibility and redaction.

Exit criteria:

- Every request has a trace.
- `/debug` returns the latest relevant trace.
- Large payloads and secrets are not exposed.

Not in this phase:

- production switch

## Phase 11: Data Import And Migration

Goal: support importing previously exported user/runtime data into storage through documented import formats.

Tasks:

- Write one-way import readers for documented export formats.
- Migrate:
  - user profiles
  - HR zones
  - history events
  - chat summaries
  - workout index
  - active workouts
  - raw GPX references
- Validate ownership and counts.
- Produce migration report.
- Add dry-run mode.
- Add tests with fixture data.

Exit criteria:

- Migration can run in dry-run and apply modes.
- Counts and key records match expectations.
- Imported raw GPX files remain intact.

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

Implement Phase 1:

- add `tests/`
- add foundation model tests
- add storage helper
- add schema load and basic insert tests
- add import hygiene test

This makes v3 a tested base before adding any feature behavior.
