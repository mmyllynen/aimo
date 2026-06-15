# Aimo Development Status

This file is the short handoff checklist for future sessions. Keep the detailed intent in the specs, and keep this file focused on what is done and what should happen next.

## Current State

Done:

- Clean v3 root is the active project root.
- Legacy implementation is isolated under ignored `legacy/`.
- Public GitHub-ready baseline exists.
- MIT license and lightweight README exist.
- Core contracts exist for canonical events, routing, workflow results, errors, and traces.
- Initial SQLite schema draft exists in `storage/schema.sql`.
- Internationalization foundation exists for `fi` and `en`.
- Config/runtime foundation exists without production integrations.
- Foundation tests cover core contracts, import hygiene, and SQLite schema loading.
- Minimal SQLite helper opens connections, applies `storage/schema.sql`, and exposes transaction boundaries.
- Repositories exist for users, HR zones, channels, history events, attachments, workouts, active workouts, workout streams/points, debug traces, and rendered artifacts.
- Repository bundle and unit-of-work wrapper exist for explicit transaction boundaries.
- Discord adapter shell normalizes fake Discord snapshots into canonical events and renders outgoing payloads without `discord.py`.
- Dispatcher skeleton persists inbound user/channel/history data and routes deterministic help/debug/noop workflows.
- Deterministic `/treenit` workflow skeleton supports list/show/active/set-active/delete/HR-zone actions against repositories.
- Dispatcher creates bounded debug traces for each request and `/debug` access is scoped by requester/admin policy.
- Trace payload redaction and count-based debug trace pruning are centralized and tested.
- LLM gateway skeleton exists with typed operations, fake client tests, schema validation, language instruction, and raw workout point guards.
- Chat workflow skeleton exists for mentioned chat requests, uses the typed LLM gateway, stores assistant replies in history, and keeps normal channel messages persistence-only/noop.
- GPX ingest foundation parses GPX bytes, derives workout points/streams, stores workouts transactionally, sets active workout, and detects duplicate uploads by owner/hash.
- Shared workout reference resolver supports latest, active, exact id, list index, date, title/kind/tag text matches, no-match, and ambiguity policy.
- Visualization foundation resolves shared workout references through a generic dataset request, dataset resolver, dataset manifest, visualization spec, spec validator, and renderer adapter pipeline. Current line and HR-zone distribution behavior now flows through that generic path.
- Workout chat foundation resolves shared workout references, sends bounded workout facts and stream manifests to the LLM, persists assistant replies, and keeps raw points out of model inputs.
- OpenAI Responses API compatible `LLMClient` adapter exists behind the typed gateway, with fake HTTP tests and no SDK dependency.
- Application runtime context wires config, translator, SQLite schema, dispatcher, admin policy, and optional real LLM gateway without starting Discord.
- `aimo.py --check-services --config aimo.conf.example` validates storage schema and service wiring without production integrations.
- Discord attachment download boundary hydrates supported GPX attachments with size/type checks before dispatch, using fake HTTP tests and no `discord.py` dependency.
- Raw GPX and rendered visualization artifacts can be written under configured storage roots with path traversal protection.
- SQLite migration runner applies the current schema as version 1, supports numbered migration directories, records applied versions, and is used by application service startup.
- LLM gateway emits bounded model-call trace events into dispatch debug traces without storing prompts or model input payloads.
- Discord runtime skeleton wires message handling, outgoing text/file sends, attachment hydration, and `--run-discord` startup around the application context with optional `discord.py`.
- Discord slash command specs and registration skeleton exist for `/aimo`, `/treenit`, and `/debug`, with richer interaction option and attachment extraction tests.
- Visualization spec compiler validates requested datasets, metric aliases, transforms, encodings, required values, and renderer marks before rendering.
- Visualization dataset manifests expose a row-free model view with schema, safe stats, null counts, and allowed transforms only.
- Visualization renderer supports reusable `filter_non_null` and `rolling_average`/`smooth` transforms through the generic spec path.
- Visualization renderer supports reusable `aggregate_sum` and `aggregate_avg` transforms through the generic spec path.
- Visualization resolver supports a reusable `workout_summary` dataset for scalar workout metrics such as duration, distance, ascent, average HR, max HR, and point count.
- Visualization resolver supports reusable recent-workout comparison datasets for owner-scoped workout summary metrics through the generic spec path.
- LLM intent classification can route mentions and `/aimo syote` with bounded inputs, while deterministic explicit commands and GPX attachments keep priority and fallback remains available.
- Production preflight checks validate required secrets, storage migrations, storage writeability, LLM gateway configuration, and local `discord.py` package availability without connecting to Discord or OpenAI.
- Production cutover and manual smoke-test checklist exists in `docs/PRODUCTION_CUTOVER.md`.
- Debug traces include bounded lifecycle spans for inbound events, repository persistence, routing, workflow execution, LLM calls, visualization rendering, outbound responses, and final results.
- `/debug` exports requester/admin-scoped trace JSON with redaction, event-count summaries, and large-trace event limits.
- Documented `aimo.v3.import.v1` JSON data importer supports dry-run/apply modes for users, HR zones, history, channel summaries, workout index records, active workouts, and raw GPX references.
- Data importer validates ownership/counts, rejects conflicting primary keys, reports imported counts, and does not mutate referenced raw GPX files.
- `aimo.py --check --config aimo.conf.example` validates config and catalogs without Discord/OpenAI startup.
- `data/`, `logs/`, `artifacts/`, local config, SQLite databases, and IDE files are ignored.

Partly done:

- Discord adapter.
- Workflow handlers.
- LLM gateway.

Not done:

- Production cutover execution.

## Latest Verification

Run before handing off:

```bash
python3 -m unittest discover
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

Latest known result: all pass.

Run `python3 aimo.py --preflight --config aimo.conf` separately before production cutover with real local credentials.

## Next Step

Phase 11 data import and migration is complete for the current roadmap scope. Continue production cutover execution prep or move to Phase 12 shadow run:

- add restart/deployment script docs for the actual host and run a real Discord smoke test when credentials are available
- keep `discord.py` objects outside workflow code

Acceptance for the next completed step:

- `python3 -m unittest discover` passes
- no live model calls in tests
- LLM inputs stay bounded and schema-validated
- raw workout points stay out of LLM inputs
- runtime bootstrap remains integration-free
- no new visualization feature is implemented as a workflow-specific chart branch

## Notes

- Do not use `legacy/` as implementation guidance.
- Do not commit real `aimo.conf`, tokens, user profiles, GPX files, history, logs, generated artifacts, or SQLite databases.
- Deterministic user-facing text should use i18n translation keys.
- LLM-generated user-visible text must be instructed to use the configured language from `aimo.conf`.
