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
- `aimo.py --check --config aimo.conf.example` validates config and catalogs without Discord/OpenAI startup.
- `data/`, `logs/`, `artifacts/`, local config, SQLite databases, and IDE files are ignored.

Not done:

- Storage helper and schema loading tests.
- Repository layer.
- Discord adapter.
- LLM gateway.
- GPX parser/ingest.
- Workflow handlers.
- Visualization rendering.
- Production startup.

## Latest Verification

Run before handing off:

```bash
python3 -m unittest discover
python3 -m py_compile aimo.py core/*.py tests/*.py
python3 aimo.py --check --config aimo.conf.example
git diff --check
```

Latest known result: all pass.

## Next Step

Continue with Phase 1 foundation hardening:

- add tests for `CanonicalEvent`, routing, workflow results, errors, and traces
- add SQLite schema load test using an in-memory database
- add minimal `storage` helper that opens SQLite, applies `storage/schema.sql`, and exposes transaction boundaries
- add import hygiene test for package boundaries

Acceptance for the next completed step:

- `python3 -m unittest discover` passes
- `storage/schema.sql` loads cleanly into in-memory SQLite
- runtime bootstrap remains integration-free
- no runtime/user data is tracked by git

## Notes

- Do not use `legacy/` as implementation guidance.
- Do not commit real `aimo.conf`, tokens, user profiles, GPX files, history, logs, generated artifacts, or SQLite databases.
- Deterministic user-facing text should use i18n translation keys.
- LLM-generated user-visible text must be instructed to use the configured language from `aimo.conf`.
