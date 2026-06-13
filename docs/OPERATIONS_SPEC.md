# Aimo v3 Operations Spec

## Runtime Configuration

Required configuration:

- bot language
- bot enabled/disabled flag
- Discord token
- OpenAI API key or compatible model provider credentials
- SQLite database path
- artifact storage path
- raw GPX storage path
- admin user ids
- guild/domain policy
- model mapping per LLM operation
- max attachment size
- history retention window
- debug enablement flags

Configuration should be loaded once at startup and passed as immutable runtime config.

Foundation bootstrap may validate config and catalogs without requiring production secrets. Actual production startup must fail fast when required credentials are missing.

## Startup

Startup sequence:

1. Load config.
2. Initialize logging.
3. Open SQLite.
4. Apply migrations.
5. Ensure artifact/raw storage directories exist.
6. Build repositories and services.
7. Build LLM gateway.
8. Build Discord adapter.
9. Register slash commands.
10. Start Discord client.

Startup should fail fast on missing required secrets or invalid database migration.

## Shutdown

Shutdown should:

- stop accepting new Discord events
- finish or cancel in-flight workflows gracefully
- close database connections
- flush logs

## Logging

Logs should include:

- startup/shutdown
- Discord connection lifecycle
- request ids
- workflow names
- error categories
- model operation names
- token usage where available

Logs must not include:

- Discord token
- OpenAI API key
- raw GPX content
- full unbounded model payloads

## Debug Traces

Every request should create a trace.

Trace retention:

- keep recent traces in SQLite
- prune by count or age
- summarize large payloads

Debug export:

- available through `/debug`
- restricted to relevant user or admin
- redacted
- attached as JSON when large

## Data Retention

Recommended defaults:

- channel history: 1 year
- summaries: until channel deletion or manual cleanup
- debug traces: short operational window
- raw GPX and workouts: until user deletes them
- rendered artifacts: prune by age/count unless explicitly retained

## Artifact Storage

Artifacts:

- raw GPX files
- rendered images
- debug exports if persisted

Rules:

- store under configured artifact roots
- use ids, not user-provided filenames, for storage paths
- preserve original filename as metadata
- never expose local filesystem paths to users or models

## Deployment

Recommended production mode:

- one bot process
- SQLite database on persistent disk
- supervised by systemd, screen, or equivalent process manager
- health check command that verifies process and recent startup

## Health Checks

Health check should verify:

- process is running
- database opens
- migrations are current
- Discord client connected recently
- slash commands registered

## Backups

Backup:

- SQLite database
- raw GPX storage
- artifact metadata if not fully in database

Backup before:

- migration
- production cutover
- destructive cleanup

## Restore And Recovery

Recovery requirements before v3 cutover:

- v3 can run in disabled or shadow mode during rollout
- v3 can be disabled by config flag during rollout
- import is one-way but source raw data is not deleted by the importer

After final cutover:

- recovery means restoring from backup or disabling v3 public responses until fixed

## Admin Operations

Admin-only capabilities:

- broader debug lookup
- health report
- migration dry-run/apply
- trace pruning

All admin operations must check configured admin user ids.

## Common User-Facing Error Templates

```text
En saanut mallilta vastausta juuri nyt. Yritä hetken päästä uudelleen.
```

```text
En löytänyt tuolla viitteellä treeniä.
```

```text
Tässä treenissä ei ole pyydettyä mittaria: {metric}.
```

```text
Tuo liite ei näytä kelvolliselta GPX-tiedostolta.
```

```text
Visualisoinnin piirtäminen epäonnistui. Data tallessa, mutta kuvaa ei saatu muodostettua.
```
