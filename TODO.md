# Aimo TODO

This is the short working backlog. Keep product intent in `docs/` and keep this list concrete enough to pick up in a coding session.

## Current State

Aimo is production-capable and runs as a Discord bot with SQLite storage, typed workflows, bounded LLM calls, GPX ingest, workout management, visualization, debug traces, and Finnish/English deterministic messages.

Operational guardrails currently in place:

- Direct messages are rejected before dispatch.
- Guild/channel allowlists are enforced before dispatch.
- The bot responds only to mentions and slash commands.
- Normal guild messages may still be stored as channel history and remain no-op responses.
- Users are tracked as `observed` until their first mention/slash interaction, then `interacted`.
- Admin users receive a DM on the first active user interaction.
- Raw GPX and full workout point arrays stay out of routing/model planning inputs.
- Invalid LLM visualization intents get one bounded revision attempt using compact manifests and structured validation errors.
- Natural-language visualization meaning is handled by LLM contracts; Python stores safe context, validates canonical ids, and renders.
- Current workout context updates through GPX ingest, `/treenit nayta`, and explicit LLM context-update fields after safe workout resolution.
- `/treenit poista` requires a 60-second same-user button confirmation before deleting a workout.
- Visualization rendering uses a shared chart frame, fixed legend sidebar, generic color metadata, and common value formatting across line, bar, and pie charts.
- Tests use fake LLM/HTTP/Discord boundaries and do not make live OpenAI calls.

## Priority 1: Ship User-Visible Features

- Add workout rename/tag editing through deterministic slash commands.
- Add workout import/export commands for a user's own workout index and metadata.
- Add more natural chart requests: monthly totals, weekly distance trend, HR-zone trends, and latest-vs-previous comparison.
- Add GPX ingest support for multiple files in one request with one concise summary.
- Add a user-visible privacy/help note explaining stored history, workouts, debug traces, and deletion options.

## Priority 2: Reliability And Operations

- Add a production smoke-test script that checks config, migrations, Discord command registration, mention handling, slash handling, and log health without using live OpenAI in tests.
- Add an operator health command or CLI report for process status, database path, migration version, configured guilds, and recent errors.
- Add retention jobs for debug traces, rendered artifacts, and old channel history according to config.
- Add backup/restore runbook and a tested SQLite backup command.
- Add a startup check that warns if `aimo.conf` contains `allow_direct_messages = true`, since runtime rejects DMs regardless.
- Add better failure logging around admin-DM delivery without exposing user content.
- Add metrics around LLM latency, model timeout, render failures, and GPX ingest failures.

## Priority 3: Data And Model Quality

- Implement channel summary refresh so chat context does not rely only on recent raw history rows.
- Add user profile facts beyond HR zones where useful, with explicit privacy boundaries.
- Expand workout fact summaries for coaching while preserving the no-raw-points LLM rule.
- Move workout-chat workout reference interpretation fully behind the typed LLM selector contract; keep Python resolver limited to structured selector resolution.
- Add more deterministic intent shortcuts before LLM routing for common Finnish/English workout and visualization requests.
- Improve model fallback copy so unsupported or unavailable model states still give useful next steps.
- Add schema/version handling for visualization specs before introducing substantially richer chart capabilities.

## Priority 4: Code Health

- Split `app/dispatcher.py` into persistence, routing, tracing, and dispatch orchestration helpers once the next feature work touches it.
- Split `adapters/discord/runtime.py` into command registration, message handling, interaction handling, and admin notification helpers.
- Keep repository APIs narrow; add query helpers only when a workflow needs them.
- Review config fields that are now policy-disabled, especially `allow_direct_messages`, and decide whether to remove or keep as a rejected legacy field.
- Keep import hygiene tests strict so active code does not depend on `legacy/` or Discord objects outside adapters.

## Verification Checklist

Run before handoff:

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

For production changes, also run:

```bash
python3 aimo.py --preflight --config aimo.conf
```

## Standing Rules

- Do not commit real `aimo.conf`, tokens, user profiles, GPX files, history, logs, generated artifacts, or SQLite databases.
- Deterministic user-facing text uses i18n translation keys.
- LLM-generated user-visible text must be instructed to use the configured language.
- Keep model inputs bounded and schema-validated.
- Keep raw GPX and workout point data out of model planning inputs.
- Keep Discord-specific objects at the adapter boundary.
