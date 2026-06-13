# Production Cutover

This checklist is the v3 production readiness path. It does not rely on legacy code.

## Local Config

Create a local, uncommitted `aimo.conf` from `aimo.conf.example`.

Required production values:

- `[discord] token`
- `[openai] api_key`
- `[openai] model`
- `[storage] database_path`
- `[storage] artifact_path`
- `[storage] raw_gpx_path`
- `[admin] user_ids`

Do not commit `aimo.conf`, runtime databases, GPX files, logs, or generated artifacts.

## Preflight

Run before starting the bot:

```bash
python3 aimo.py --config aimo.conf --preflight
```

The preflight checks:

- i18n catalogs
- production config and required secrets
- SQLite schema migration/queryability
- raw GPX storage writeability
- rendered artifact storage writeability
- OpenAI gateway configuration
- local `discord.py` package availability

For local CI only, where `discord.py` is intentionally not installed:

```bash
python3 aimo.py --config aimo.conf --preflight --allow-missing-discord-package
```

## Start

Production start command:

```bash
python3 aimo.py --config aimo.conf --run-discord
```

Expected behavior:

- startup fails fast if Discord or OpenAI credentials are missing
- startup fails fast if `discord.py` is unavailable
- runtime data is written only under configured storage paths
- workflow code receives canonical events, not Discord objects

## Manual Smoke Test

After startup, verify these in a private test channel first:

- `@AImo apua` returns help
- `/debug` returns an ephemeral trace attachment
- `/treenit listaa` returns either an empty list message or owned workouts
- upload a small GPX file with an Aimo mention; it is stored as a workout
- `/treenit aktiivinen` shows the uploaded workout
- `@AImo analysoi viimeisin treeni` answers without asking which workout
- `@AImo piirrä viimeisimmästä treenistä syke ajan funktiona` returns an image or a precise missing-metric error

## Rollback

Before switching real traffic:

- keep a copy of the previous runtime directory
- keep a database backup
- keep the previous process restart command available

If v3 fails critical smoke tests:

- stop the v3 process
- restore the previous process
- keep v3 logs and `/debug` traces for diagnosis

## Cutover Done Criteria

Cutover is done when:

- preflight passes
- bot logs into Discord
- slash commands are registered
- the smoke test passes
- no secrets appear in logs or debug traces
- user-owned workout checks pass with at least two distinct test users or fixtures
