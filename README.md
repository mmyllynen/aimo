# Aimo

Aimo is a multilingual Discord bot for concise channel chat, workout coaching, GPX ingest, workout management, and natural-language workout visualizations.

The active implementation is this repository root. The bot runs from local configuration, stores data in SQLite, keeps Discord-specific objects at the adapter boundary, and routes all model usage through typed LLM gateway contracts.

## Current Capabilities

- Public replies to `@Aimo` mentions.
- Slash commands: `/aimo`, `/treenit`, `/debug`.
- GPX upload and duplicate detection.
- User-owned workout storage, active workout selection, deletion, and heart-rate zone configuration.
- Workout chat and chart generation from bounded workout facts and validated visualization specs.
- Bounded debug traces with redaction and requester/admin access rules.
- Finnish and English deterministic message catalogs.
- Production preflight checks and local JSON data import.

Direct messages are not accepted. Guild/channel allowlists are enforced before dispatch. Normal guild messages can still be stored as bounded channel history, but the bot only responds to mentions and slash commands.

## Repository Layout

```text
aimo.py                 CLI entrypoint
aimo.conf.example       local config template
core/                   canonical events, config, routing, i18n, workflow contracts
app/                    dispatcher, runtime wiring, preflight, policy, redaction
adapters/discord/       Discord normalization, runtime, command registration, outgoing rendering
workflows/              chat, help, debug, GPX, workout management, workout chat, visualization
storage/                SQLite schema, migrations, repositories, import
workout/                GPX parsing, ingest, workout reference resolution
visualization/          datasets, specs, renderer, service
llm/                    typed gateway, operations, OpenAI-compatible client
tests/                  unit and adapter tests
docs/                   product and engineering specs
```

Do not use `legacy/` as implementation guidance unless explicitly doing import or comparison work.

## Configuration

Runtime configuration is read from `aimo.conf`, which is intentionally ignored by git. Start from `aimo.conf.example`.

Useful checks:

```bash
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
python3 aimo.py --preflight --config aimo.conf
```

Run Discord:

```bash
python3 aimo.py --config aimo.conf --run-discord
```

Import documented JSON data:

```bash
python3 aimo.py --config aimo.conf --import-data export.json --dry-run
python3 aimo.py --config aimo.conf --import-data export.json
```

## Development

Read `TODO.md` first for current priorities. Keep behavior aligned with the specs in `docs/`.

Before handing off changes:

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

## Security

Never commit local config, secrets, tokens, user data, GPX files, logs, SQLite databases, or generated artifacts.
