# Aimo Operations

This file covers runtime configuration, local checks, data import, retention, backups, and operational guardrails.

## Configuration

Runtime config is loaded from `aimo.conf`, which is intentionally untracked.

Important sections:

- `[bot]`: language and enabled flag
- `[discord]`: token, allowed guild ids, optional allowed channel ids
- `[openai]`: API key/model/timeout/token budget
- `[storage]`: SQLite database, raw GPX root, artifact root
- `[admin]`: Discord admin user ids
- `[limits]`: attachment limits
- `[history]`: retention policy
- `[debug]`: debug enablement
- `[maps]`: tile provider settings
- `[renderers]`: renderer selection by chart type

Production startup must require Discord token, allowed guild ids, and OpenAI key. Local checks may run without secrets. Direct messages are rejected by runtime policy even if older config files contain an `allow_direct_messages` field.

## Startup

Startup sequence:

1. Load and validate config.
2. Initialize logging.
3. Open SQLite and apply migrations.
4. Ensure raw GPX and artifact directories exist.
5. Build repositories and application context.
6. Build optional LLM gateway.
7. Build Discord runtime.
8. Register/sync slash commands.
9. Start Discord client.

Startup should fail fast on invalid config, missing production secrets, invalid migrations, or missing `discord.py` in production mode.

## Checks

Default local checks:

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```

Production-oriented checks:

```bash
python3 aimo.py --preflight --config aimo.conf
python3 scripts/production_smoke.py --config aimo.conf --log logs/bot.log
```

`scripts/production_smoke.py` must not make live OpenAI calls. It validates config loading, SQLite schema creation on a temporary database, Discord command spec registration, deterministic mention/slash dispatch paths, and recent log health.

## Logging And Traces

Logs should include startup/shutdown, Discord lifecycle, command sync results, event ids, workflow names/statuses, typed error categories, and model operation latency where available.

Logs and traces must not include Discord tokens, OpenAI keys, raw GPX content, full point arrays, full unbounded model payloads, or secrets.

Every dispatched event creates a bounded debug trace. `/debug` exports requester/admin-authorized traces with redaction and JSON attachment behavior for large outputs.

## Retention

Recommended policy:

- channel history: configured retention window
- debug traces: short operational window
- raw GPX/workouts: until user deletion or explicit retention policy
- rendered artifacts: prune by age/count unless explicitly retained

Retention jobs for debug traces, rendered artifacts, and old channel history are backlog items.

## Backups

Back up the SQLite database, raw GPX directory, and rendered artifacts if artifacts must remain reproducible.

Backup before migrations, destructive cleanup, large imports, and production deployments that change schema or storage behavior. Restore should be tested against a copied database, never first against production.

## Data Import

Aimo supports one-way conservative JSON import. The importer validates ownership before writing, supports dry-run mode, reports imported counts, rejects conflicting primary keys, does not delete source data, and does not copy/move/mutate raw GPX files.

Current format id:

```text
aimo.v3.import.v1
```

Top-level collections are optional lists:

```json
{
  "format": "aimo.v3.import.v1",
  "users": [],
  "channels": [],
  "channel_summaries": [],
  "heart_rate_zones": [],
  "history_events": [],
  "attachments": [],
  "workouts": [],
  "active_workouts": []
}
```

Ownership/link rules:

- `channels` must exist before channel-bound rows.
- `users` must exist before user-owned rows.
- `heart_rate_zones.user_id` must reference `users`.
- `history_events.channel_id` must reference `channels`; optional `user_id` must reference `users`.
- `attachments.owner_user_id` must reference `users`; optional `channel_id` must reference `channels`.
- `workouts.owner_user_id` must reference `users`; optional `source_attachment_id` must reference an attachment owned by the same user.
- `active_workouts` must reference a workout owned by the same user.

`attachments.raw_path` is stored as a reference only. `source_path` may be included for operator reporting, but the importer does not read or mutate it.

Minimum required fields:

| Collection | Required fields |
| --- | --- |
| `users` | `user_id`, either `first_seen_at` or `last_seen_at` |
| `channels` | `channel_id` |
| `channel_summaries` | `channel_id`, `summary`, `updated_at` |
| `heart_rate_zones` | `user_id`, `zone_key`, `label` |
| `history_events` | `history_id`, `channel_id`, `role`, `event_type`, `created_at` |
| `attachments` | `attachment_id`, `owner_user_id`, `filename`, `sha256`, `raw_path`, `created_at` |
| `workouts` | `workout_id`, `owner_user_id`, `title`, `kind`, `created_at` |
| `active_workouts` | `user_id`, `workout_id`, `updated_at` |

Run import:

```bash
python3 aimo.py --config aimo.conf --import-data export.json --dry-run
python3 aimo.py --config aimo.conf --import-data export.json
```

The importer opens the configured SQLite database and applies migrations before validation/import.

## Future Storage Encryption

Encryption at rest is a backlog item, not an active runtime guarantee. The intended direction is application-level envelope encryption for raw GPX, rendered artifacts, channel history content, debug payloads, and eventually detailed workout point streams, while keeping ids, ownership fields, timestamps, content hashes, and summary metrics plaintext for lookup and retention.

Any future rollout must be staged with dual-read support, explicit config, backup/key-management documentation, readback verification, and no automatic plaintext cleanup until a backup and migration are verified.
