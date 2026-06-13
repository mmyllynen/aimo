# AGENTS.md for Aimo

## Scope

This directory is the standalone source of truth for Aimo.

Use the specifications in this directory as the source of truth. Do not use code or documents outside the files and packages described here as guidance unless the user explicitly asks for import or comparison work.

The goal is to build Aimo from these local specifications:

- `PRODUCT_SPEC.md`
- `COMMAND_SPEC.md`
- `WORKOUT_SPEC.md`
- `VISUALIZATION_SPEC.md`
- `LLM_CONTRACTS.md`
- `OPERATIONS_SPEC.md`
- `REWRITE_FOUNDATION.md`
- `REWRITE_PLAN.md`
- `V3_ROADMAP.md`

## Product Intent

Aimo is a Finnish-speaking Discord bot for:

- concise public chat replies
- workout coaching conversation
- GPX ingest
- workout management
- heart-rate zone configuration
- natural-language workout visualizations
- structured debug traces

The bot should be dependable and workflow-driven. LLMs may interpret language and draft text, but deterministic application code owns state transitions, data access, validation, rendering, permissions, and error handling.

## Current State

The project currently contains:

- architecture and product specs
- foundation dataclasses/enums
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
- Fail with typed error categories and stable Finnish user-facing responses.

## Roadmap

Follow `V3_ROADMAP.md`.

The immediate next phase is Phase 1: Foundation Hardening:

- add `tests/`
- test foundation models
- add storage helper
- test `schema.sql`
- test import hygiene

## Verification

When changing Aimo:

- run Python syntax checks for touched modules
- run tests once they exist
- verify SQLite schema loading when schema changes

## Non-Goals

- Do not preserve behavior unless it is required by the product specs.
- Do not wire the bot into live Discord before roadmap cutover phases.
- Do not use live OpenAI calls in normal tests.
