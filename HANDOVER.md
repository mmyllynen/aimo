# Aimo Handover

This file is the fast entrypoint for the next session. It captures the current implementation direction and the traps to avoid. `TODO.md` remains the short status checklist; specs under `docs/` remain the product source of truth.

## Current State

Approximate feature parity: 80%.

The current tree is the clean v3 implementation. Do not use `legacy/` or old archived material as implementation guidance.

Major foundations are in place:

- config/runtime bootstrap in `aimo.py`, `core/`, and `app/runtime.py`
- SQLite schema, migration runner, repositories, and unit-of-work in `storage/`
- Discord normalization/runtime skeleton in `adapters/discord/`
- typed LLM gateway, fake client tests, and OpenAI Responses API adapter in `llm/`
- dispatcher, traces, debug workflow, chat workflow, GPX ingest, workout management, workout chat, and visualization workflows
- production preflight in `app/preflight.py`
- cutover checklist in `docs/PRODUCTION_CUTOVER.md`

Tests are currently passing:

```bash
python3 -m unittest discover
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

Before production cutover, run separately with real local credentials:

```bash
python3 aimo.py --preflight --config aimo.conf
```

## Architecture Direction

Aimo is a workflow-driven Discord bot. LLMs may interpret language and draft text, but Python owns:

- state transitions
- repository access
- permissions and owner checks
- validation
- transforms
- rendering
- stable error categories
- localized deterministic user-facing text

Keep Discord-specific objects at the adapter boundary. Workflows should consume canonical events and return workflow results.

Keep model inputs bounded. Routing and visualization planning must never receive raw GPX, raw workout point rows, tokens, local config, database contents, or cross-user data.

## Visualization Direction

This is the most important current guardrail.

Aimo's visualization intent is to be a generic visualizer:

```text
user text
-> VisualizationIntent
-> DatasetRequest
-> DatasetResolver
-> DatasetManifest
-> VisualizationSpec
-> spec validator/compiler
-> renderer adapter
-> PNG artifact
```

Current implementation files:

- `visualization/datasets.py`
  - `DatasetRequest`
  - `DatasetManifest`
  - workout point dataset
  - derived HR-zone distribution dataset
- `visualization/specs.py`
  - `VisualizationSpec`
  - encoding validation against manifest
  - mark selection from data shape
- `visualization/service.py`
  - generic orchestration from intent to artifact
  - renderer adapter call
- `visualization/render.py`
  - drawing primitives for line and bar PNG output
- `workflows/visualization.py`
  - workout resolution, repository fetches, artifact persistence, user-facing errors

The old render-plan/chart-family model has been removed. Do not reintroduce:

- `chart_family`
- `RenderPlan`
- `compile_render_plan`
- workflow branches like `if user asked HR zones then render special chart`
- service branches like `if spec kind is this product feature then use custom path`

Allowed explicit code:

- renderer marks/primitives, such as `line` and `bar`
- dataset definitions, such as a derived HR-zone dataset
- canonical metric aliases
- validated transform names

Those are infrastructure primitives, not product-level chart branches. New visualization behavior should be added by extending reusable datasets, manifests, specs, transforms, encodings, or renderer primitives.

## Next Good Steps

High-value next steps:

- Add generic visualization transforms:
  - `filter_non_null`
  - smoothing / rolling average
  - aggregation
  - comparison datasets
  - workout summary datasets
- Add dataset manifest tests proving model-visible planning inputs contain schema/stats only, not raw rows.
- Add production host restart/deployment docs and run the real Discord smoke test when credentials are available.
- Add chat follow-up context and summary refresh.
- Add GPX-derived features:
  - splits
  - HR-zone enrichment at ingest time
  - better workout tags

## Do Not Do

- Do not use `legacy/` as guidance.
- Do not add visualization features as one-off workflow/service branches.
- Do not pass raw workout points or GPX rows to LLM operations.
- Do not use live OpenAI or live Discord in unit tests.
- Do not commit `aimo.conf`, tokens, user data, GPX files, logs, generated artifacts, or SQLite databases.
- Do not put Discord.py objects into workflows.
- Do not add deterministic user-facing text without i18n keys.
- Do not weaken owner checks around workouts, artifacts, debug traces, or history.

## Current Git Context

The current checkpoint should be committed after this handover. The commit includes multiple foundations since the previous checkpoint:

- OpenAI client adapter
- application runtime context
- Discord attachment hydration/runtime/slash registration skeleton
- raw/artifact file storage
- SQLite migration runner
- LLM trace events
- LLM intent routing
- shared workout reference resolver
- production preflight and cutover docs
- generic visualization dataset/spec pipeline

If continuing from this commit, start by reading:

1. `HANDOVER.md`
2. `TODO.md`
3. `docs/VISUALIZATION_SPEC.md` for visualizer work
4. `docs/V3_ROADMAP.md` for phase-level work
5. touched module tests for the feature area being changed
