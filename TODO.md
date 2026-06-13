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
- Visualization foundation resolves latest/active/id workouts, renders line-chart PNG files from stored point data, supports metric aliases and normalized secondary series, and returns precise missing-primary-metric errors.
- Workout chat foundation resolves latest/active/id workouts, sends bounded workout facts and stream manifests to the LLM, persists assistant replies, and keeps raw points out of model inputs.
- `aimo.py --check --config aimo.conf.example` validates config and catalogs without Discord/OpenAI startup.
- `data/`, `logs/`, `artifacts/`, local config, SQLite databases, and IDE files are ignored.

Partly done:

- Discord adapter.
- Workflow handlers.
- LLM gateway.

Not done:

- Production startup.

## Latest Verification

Run before handing off:

```bash
python3 -m unittest discover
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
git diff --check
```

Latest known result: all pass.

## Next Step

Continue Phase 6 live LLM adapter, Phase 9 visualization hardening, or production runtime binding:

- add live OpenAI-compatible `LLMClient`, or
- harden visualization with render-plan validation, richer chart families, artifact file writing, or HR-zone distribution charts
- add production Discord runtime binding and attachment download boundary
- keep `discord.py` objects outside workflow code

Acceptance for the next completed step:

- `python3 -m unittest discover` passes
- no live model calls in tests
- LLM inputs stay bounded and schema-validated
- raw workout points stay out of LLM inputs
- runtime bootstrap remains integration-free

## Notes

- Do not use `legacy/` as implementation guidance.
- Do not commit real `aimo.conf`, tokens, user profiles, GPX files, history, logs, generated artifacts, or SQLite databases.
- Deterministic user-facing text should use i18n translation keys.
- LLM-generated user-visible text must be instructed to use the configured language from `aimo.conf`.
