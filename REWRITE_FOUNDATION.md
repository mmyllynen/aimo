# Aimo Foundation

This document turns the rewrite plan into the first concrete technical boundary. It defines the stable contracts for Aimo without integrating them into a live runtime.

## Scope

The foundation contains:

- canonical inbound event model
- workflow routing target model
- workflow result model
- application error categories
- trace event model
- initial SQLite schema
- lightweight Python skeleton for these contracts

The foundation does not contain:

- Discord runtime integration
- OpenAI integration
- GPX parsing implementation
- chart rendering implementation
- migration/import from documented export data
- production startup changes

## Canonical Event Model

Every external input should be normalized into a `CanonicalEvent`.

Required fields:

- `event_id`: stable unique id for tracing and idempotency
- `source`: `discord_message`, `discord_slash`, `discord_attachment`, `system`
- `kind`: `message`, `mention`, `slash_command`, `attachment`, `scheduled`
- `guild_id`
- `channel_id`
- `user_id`
- `user_name`
- `text`
- `attachments`
- `created_at`
- `metadata`

The Discord adapter owns conversion into this model. Workflows should not depend on Discord.py objects.

## Workflow Target Model

Routing chooses one workflow target:

- `chat`
- `workout_chat`
- `gpx_ingest`
- `workout_management`
- `visualization`
- `debug`
- `help`

Routing may attach bounded slots such as:

- `workout_selector`
- `metric_names`
- `date_range`
- `command`
- `chart_goal`

Routing must not attach raw workout points, raw GPX data, or large history dumps.

## Workflow Result Model

Each workflow returns a `WorkflowResult`.

Result statuses:

- `success`
- `clarify`
- `user_error`
- `system_error`
- `forbidden`
- `noop`

Result payloads:

- `messages`: Discord-ready outgoing messages
- `state_updates`: persistence operations the application layer can commit
- `trace_events`: structured trace entries
- `error`: optional typed application error

The result model separates "what happened" from "how Discord sends it".

## Error Category Model

All user-visible failures should map to stable categories:

- `unsupported_attachment`
- `invalid_gpx`
- `no_matching_workout`
- `missing_metric`
- `ambiguous_workout`
- `visualization_plan_invalid`
- `render_failed`
- `model_unavailable`
- `permission_denied`
- `storage_error`
- `unexpected`

Each category should have a Finnish response template later. The foundation only defines the categories.

## Trace Model

Every request should produce trace events.

Trace fields:

- `trace_id`
- `event_id`
- `workflow`
- `stage`
- `level`
- `message`
- `payload`
- `created_at`

Large payloads must be summarized before trace export. Secrets must not be stored.

## SQLite Foundation

SQLite is the recommended v3 persistence layer. The first schema should support:

- users and profile metadata
- HR zones
- channels and summaries
- history events
- workouts and active workout mapping
- raw attachment metadata
- workout streams and points
- debug traces
- rendered artifacts

Schema evolution should use numbered migrations later. The foundation includes a single initial schema draft in `storage/schema.sql`.

## Skeleton Layout

Initial skeleton:

```text
REWRITE_PLAN.md
REWRITE_FOUNDATION.md
core/
  __init__.py
  events.py
  routing.py
  workflows.py
  errors.py
  trace.py
storage/
  schema.sql
```

This layout is intentionally small. It defines contracts only.

## Next Acceptance Criteria

The foundation task is complete when:

- all skeleton modules import cleanly
- dataclasses/enums model the contracts above
- schema.sql can be read as the initial v3 storage draft
- no production behavior changes until the cutover phase explicitly wires the runtime
