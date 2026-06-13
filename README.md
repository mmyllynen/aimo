# Aimo

Aimo is a planned multilingual Discord bot for chat, workout tracking, GPX-based activity analysis, and workout visualizations.

This repository currently contains the clean v3 foundation: product specs, architecture notes, core contracts, and an initial SQLite schema. It is not yet a runnable bot.

## Current Status

The project is at the foundation stage.

Included:

- product and command specifications
- workout and visualization specifications
- LLM operation contracts
- operations and roadmap documents
- canonical event, routing, workflow, error, and trace dataclasses
- internationalization skeleton for Finnish and English bot-owned messages
- initial SQLite schema draft

Not included yet:

- Discord runtime integration
- OpenAI/model gateway implementation
- GPX parser implementation
- workflow handlers
- chart renderer
- production startup

## Repository Layout

```text
AGENTS.md
PRODUCT_SPEC.md
COMMAND_SPEC.md
WORKOUT_SPEC.md
VISUALIZATION_SPEC.md
LLM_CONTRACTS.md
OPERATIONS_SPEC.md
I18N_SPEC.md
REWRITE_FOUNDATION.md
REWRITE_PLAN.md
V3_ROADMAP.md
aimo.conf.example
core/
storage/
tests/
```

## Configuration

Runtime configuration will be read from `aimo.conf`, which is intentionally ignored by git.

Use `aimo.conf.example` as the starting point:

```ini
[bot]
language = fi
```

Supported language values are `fi` and `en`. Missing config defaults to Finnish.

## Development Direction

Follow `V3_ROADMAP.md`. The immediate next milestone is foundation hardening:

- add tests
- add a minimal SQLite storage helper
- verify schema loading and basic inserts
- keep model calls behind typed contracts
- keep Discord-specific objects at the adapter boundary

## Security

Do not commit local configuration, secrets, tokens, runtime data, logs, SQLite databases, or generated artifacts. The `.gitignore` is set up to exclude those by default.
