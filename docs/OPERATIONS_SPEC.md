# Aimo Operations Spec

## Configuration

Runtime config is loaded from `aimo.conf`.

Important sections:

- `[bot]`: language and enabled flag
- `[discord]`: token, allowed guild ids, optional allowed channel ids
- `[openai]`: API key/model/timeout/token budget
- `[storage]`: SQLite database, raw GPX root, artifact root
- `[admin]`: Discord admin user ids
- `[limits]`: attachment limits
- `[history]`: retention policy
- `[debug]`: debug enablement

Production startup must require Discord token, allowed guild ids, and OpenAI key. Local checks may run without secrets.

Direct messages are rejected by runtime policy. `allow_direct_messages` may exist in older config files, but it must not enable DM use.

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

## Runtime Policy

- One bot process per production config.
- Discord events are normalized into canonical events at the adapter boundary.
- Workflows do not receive Discord objects.
- Guild/channel allowlists are checked before dispatch.
- Normal guild messages may be stored as no-op history.
- Mention/slash interactions can produce responses.
- First active user interaction is tracked separately from passive observation and notifies admins by DM.

## Logging

Logs should include:

- startup/shutdown
- Discord connection lifecycle
- command sync results
- event ids
- workflow names/statuses
- error categories
- model operation names and latency where available

Logs must not include:

- Discord token
- OpenAI API key
- raw GPX content
- full unbounded model payloads
- full workout point arrays

## Debug Traces

Every dispatched event creates a bounded trace.

Trace exports:

- available through `/debug`
- restricted to requester/admin policy
- redacted
- attached as JSON when large

Trace retention should be pruned by count and later by configurable age.

## Data Retention

Recommended defaults:

- channel history: configured retention window
- debug traces: short operational window
- raw GPX/workouts: until user deletion or explicit retention policy
- rendered artifacts: prune by age/count unless explicitly retained

Retention jobs are a current backlog item.

## Storage And Backups

Back up:

- SQLite database
- raw GPX directory
- rendered artifacts if they must remain reproducible

Backup before:

- migrations
- destructive cleanup
- large import
- production deployment that changes schema or storage behavior

Restore should be tested against a copied database, never first against production.

## Health Checks

Health checks should verify:

- bot process exists
- database opens and migration version is current
- configured storage roots are writable
- Discord slash commands sync successfully
- recent logs do not show startup loops

Current CLI checks:

```bash
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
python3 aimo.py --preflight --config aimo.conf
```

## Admin Operations

Admin-only capabilities:

- broader debug lookup
- future health report
- future trace pruning
- future migration/import commands that mutate shared state

All admin operations must check configured admin user ids.
