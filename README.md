# Aimo

Aimo is a multilingual Discord bot rewrite for chat, workout tracking, GPX-based activity analysis, and workout visualizations.

This repository contains the clean v3 implementation. It is still pre-production, but the runtime, storage, workflow, LLM, GPX, visualization, and Discord adapter skeletons are now testable.

## Current Status

Included:

- product, command, workout, visualization, LLM, and operations specs
- canonical event, routing, workflow, error, and trace contracts
- Finnish and English i18n catalogs
- SQLite schema, migration runner, repositories, and unit-of-work boundaries
- Discord adapter/runtime skeleton without Discord objects in workflows
- typed LLM gateway and OpenAI Responses API adapter
- GPX ingest, workout management, workout chat, debug, and visualization workflow foundations
- production preflight checks

Not included yet:

- complete production cutover validation
- full visualization parity
- full follow-up context and summary refresh
- data import from any previous runtime exports

## Repository Layout

```text
AGENTS.md
TODO.md
LICENSE.md
aimo.conf.example
aimo.py
core/
app/
adapters/
docs/
llm/
storage/
tests/
visualization/
workflows/
workout/
```

## Configuration

Runtime configuration will be read from `aimo.conf`, which is intentionally ignored by git.

Use `aimo.conf.example` as the starting point:

```ini
[bot]
language = fi
```

Supported language values are `fi` and `en`. Missing config defaults to Finnish.

Validate local config without starting integrations:

```bash
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
```

Run production readiness checks against a local uncommitted `aimo.conf`:

```bash
python3 aimo.py --config aimo.conf --preflight
```

Start Discord runtime:

```bash
python3 aimo.py --config aimo.conf --run-discord
```

## Development Direction

Follow `TODO.md` for current handoff status and `docs/V3_ROADMAP.md` for phase-level scope. Production cutover details live in `docs/PRODUCTION_CUTOVER.md`.

## Security

Do not commit local configuration, secrets, tokens, runtime data, logs, SQLite databases, or generated artifacts. The `.gitignore` is set up to exclude those by default.
