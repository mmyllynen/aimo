# AGENTS.md for Aimo

## Scope

This directory is the standalone source of truth for Aimo.

Use only the active packages and documents in this tree as implementation guidance. Do not use `legacy/` or documents outside this tree unless the user explicitly asks for import or comparison work.

## Read First

- `LOCAL.md` when present: local-only environment notes. Read before operational/deployment work. It is intentionally git-ignored and must not be committed.
- `README.md`: repository overview and common commands.
- `TODO.md`: current prioritized backlog.
- `HANDOVER.md`: current session handoff and smoke-test notes.
- `docs/SPEC.md`: durable product, workflow, runtime, privacy, and visualization contract.
- `docs/LLM.md`: typed LLM operation contracts.
- `docs/OPERATIONS.md`: config, checks, import, retention, backup, and operational rules.

## Core Rules

- Deterministic application code owns state transitions, data access, validation, rendering, permissions, and error handling.
- LLMs may interpret language and draft prose only through typed gateway contracts.
- LLM = intelligence: it interprets natural language and returns formal typed intent/specification.
- Python = engine: it executes typed intent/specification, validates inputs, owns state, storage, rendering, permissions, and errors.
- Do not add phrase parsers, keyword heuristics, regexes, or `if user text says X then do Y` logic for natural-language intent in Python.
- The only allowed Python-side natural-text controls are the formal override syntaxes explicitly defined for this project: plustägit (`+word`) add something, miinustägit (`-word`) remove/disable something, and tarkenteet (`key=value`, including supported aliases) set bounded values. Slash-command names, subcommands, and options are also formal UI fields, not natural-language parsing.
- If existing code appears to perform natural-language intent interpretation in Python outside plustägit, miinustägit, tarkenteet, or slash-command fields, stop and flag it to the user before extending or depending on that behavior.
- Keep raw GPX and full workout point arrays out of routing/model planning inputs.
- Keep Discord-specific objects at the adapter boundary.
- Make workflow code operate on canonical events and workflow results.
- Use SQLite through the storage helpers/repositories defined here.
- Deterministic bot-owned messages must use i18n translation keys.
- Fail with typed error categories and stable localized user-facing responses.
- Do not use live OpenAI calls in normal tests.
- Do not commit `LOCAL.md`, `aimo.conf`, tokens, SQLite databases, GPX files, logs, artifacts, or other local runtime data.

## Runtime Invariants

- Direct messages are rejected.
- Guild/channel allowlists are enforced before dispatch.
- The bot replies only to mentions and slash commands.
- Normal guild messages may be stored as history but remain no-op responses.
- First active user interaction is tracked separately from passive observation.

## Change Discipline

- Prefer adding tests before implementing behavior.
- Do not modify unrelated files unless explicitly requested.
- Avoid internal polish that does not move a product, reliability, data-quality, or testability goal forward.
- Keep repository APIs narrow; add helpers only when a workflow needs them.

## Verification

When changing Aimo:

- run Python syntax checks for touched modules
- run relevant tests, and the full test suite for shared dispatcher/storage/runtime changes
- validate i18n catalogs when user-facing deterministic text changes
- verify SQLite schema loading/migrations when schema changes
- follow `docs/OPERATIONS.md` for full handoff and production checks
