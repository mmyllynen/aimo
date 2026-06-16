# Aimo Handover

This is the fast entrypoint for a new session. This repository is the source of truth for code and tracked templates.

## Runtime

- Production host: configured outside version control.
- Production directory: configured outside version control.
- Runtime command: `python3 aimo.py --config aimo.conf --run-discord`
- Watchdog cron: use the local deployment directory and environment-specific `AIMO_*` variables.
- Local config and runtime data are intentionally untracked.

Useful local deployment checks:

```bash
pgrep -af 'python3 .*aimo.py|check-restart.sh' || true
tail -n 80 logs/bot.log
./check-restart.sh --force
```

## Development Focus

Read `TODO.md` first. Current priorities are user-visible workout features, production smoke/health tooling, retention/backup operations, and better bounded context.

## Guardrails

- Do not use `legacy/` as implementation guidance unless explicitly asked.
- Do not commit `aimo.conf`, tokens, SQLite databases, GPX files, logs, or artifacts.
- Direct messages are rejected by runtime policy.
- Normal guild messages may be stored as history but should not trigger replies.
- First active user interaction is tracked separately from passive history observation.
- Keep raw GPX and workout point rows out of model planning inputs.

## Verification

Default handoff checks:

```bash
python3 -m unittest
python3 -m py_compile aimo.py adapters/*.py adapters/discord/*.py app/*.py core/*.py llm/*.py storage/*.py tests/*.py visualization/*.py workflows/*.py workout/*.py
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
git diff --check
```
