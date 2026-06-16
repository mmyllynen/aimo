# AGENTS.md for Aimo

## Scope

This directory is the standalone source of truth for Aimo.

Use the specifications and active packages in this directory as guidance. Do not use `legacy/` or documents outside this tree as implementation guidance unless the user explicitly asks for import or comparison work.

Authoritative project documents:

- `README.md`
- `TODO.md`
- `docs/PRODUCT_SPEC.md`
- `docs/COMMAND_SPEC.md`
- `docs/WORKOUT_SPEC.md`
- `docs/VISUALIZATION_SPEC.md`
- `docs/LLM_CONTRACTS.md`
- `docs/OPERATIONS_SPEC.md`
- `docs/I18N_SPEC.md`
- `docs/DATA_IMPORT_SPEC.md`

## Product Intent

Aimo is a multilingual Discord bot for:

- concise public chat replies
- workout coaching conversation
- GPX ingest
- workout management
- heart-rate zone configuration
- natural-language workout visualizations
- structured debug traces

Initial supported languages are Finnish and English. The configured language comes from `aimo.conf`; deterministic bot-owned messages must use translation keys rather than hard-coded response text.

The bot should be dependable and workflow-driven. LLMs may interpret language and draft text, but deterministic application code owns state transitions, data access, validation, rendering, permissions, and error handling.

## Current State

The project contains a production-capable Discord runtime, SQLite storage, typed workflow dispatcher, GPX ingest, workout management, workout chat, visualization, debug traces, LLM gateway, and tests.

Important runtime rules:

- Direct messages are rejected.
- Guild/channel allowlists are enforced before dispatch.
- The bot replies only to mentions and slash commands.
- Normal guild messages may be stored as history but remain no-op responses.
- First active user interaction is tracked separately from passive observation.

## Development Rules

- Do not import modules outside the current Aimo package boundaries.
- Do not modify unrelated files unless explicitly requested.
- Prefer adding tests before implementing behavior.
- Keep model calls behind typed LLM gateway contracts.
- Keep raw GPX and workout point data out of routing/model planning inputs.
- Use SQLite through the storage helpers/repositories defined here.
- Keep Discord-specific objects at the adapter boundary.
- Make workflow code operate on canonical events and workflow results.
- Fail with typed error categories and stable localized user-facing responses.
- Do not use live OpenAI calls in normal tests.

## Roadmap

Use `TODO.md` as the current prioritized backlog.

Avoid work that only polishes internal structure without moving a product, reliability, data-quality, or testability goal forward.

## Verification

When changing Aimo:

- run Python syntax checks for touched modules
- run relevant tests, and the full test suite for shared dispatcher/storage/runtime changes
- validate internationalization catalogs when user-facing text changes
- verify SQLite schema loading/migrations when schema changes
