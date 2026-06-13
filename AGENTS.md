# AGENTS.md for Aimo

## Scope

This directory is the standalone source of truth for Aimo.

Use the specifications in this directory as the source of truth. Do not use code or documents outside the files and packages described here as guidance unless the user explicitly asks for import or comparison work.

The goal is to build Aimo from these local specifications:

- `docs/PRODUCT_SPEC.md`
- `docs/COMMAND_SPEC.md`
- `docs/WORKOUT_SPEC.md`
- `docs/VISUALIZATION_SPEC.md`
- `docs/LLM_CONTRACTS.md`
- `docs/OPERATIONS_SPEC.md`
- `docs/I18N_SPEC.md`
- `docs/REWRITE_FOUNDATION.md`
- `docs/REWRITE_PLAN.md`
- `docs/V3_ROADMAP.md`
- `TODO.md`

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

The project currently contains:

- architecture and product specs
- foundation dataclasses/enums
- internationalization foundation
- config/runtime bootstrap foundation
- initial SQLite schema draft

It is not yet wired into production and must remain independent until an explicit cutover phase.

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

## Roadmap

Follow `docs/V3_ROADMAP.md`.

Use `TODO.md` as the short current-status handoff checklist.

The immediate next phase is Phase 1: Foundation Hardening:

- test foundation models
- add storage helper
- test `schema.sql`
- test import hygiene

## Verification

When changing Aimo:

- run Python syntax checks for touched modules
- run tests once they exist
- validate internationalization catalogs when user-facing text changes
- verify SQLite schema loading when schema changes

## Non-Goals

- Do not preserve behavior unless it is required by the product specs.
- Do not wire the bot into live Discord before roadmap cutover phases.
- Do not use live OpenAI calls in normal tests.
