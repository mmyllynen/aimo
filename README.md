# Aimo

Aimo is a multilingual Discord bot for concise channel chat, workout coaching, GPX ingest, workout management, natural-language workout visualizations, and short workout overlay animations.

The active implementation is this repository root. The bot runs from local configuration, stores data in SQLite, keeps Discord-specific objects at the adapter boundary, and routes model usage through typed LLM gateway contracts.

## Capabilities

- Public replies to `@Aimo` mentions.
- Slash commands: `/aimo`, `/gpx`, `/help`, `/treenit`, `/asetukset`, `/debug`.
- GPX upload, duplicate detection, and user-owned workout storage.
- Active workout selection, button-confirmed deletion, rename/tag editing, and settings-based HR-zone configuration.
- Workout chat, route maps with waypoints/elevation overlays, period charts, social workout images, and bundled route/map/HR workout overlay animations for video editing.
- Deterministic help/privacy topics, Finnish/English catalogs, bounded debug traces, preflight checks, and JSON import.

Direct messages are rejected. Guild/channel allowlists are enforced before dispatch. Normal guild messages can be stored as bounded history, but only mentions and slash commands produce responses.

## Documentation

- [AGENTS.md](AGENTS.md): rules for agents working in this repo.
- [TODO.md](TODO.md): current prioritized backlog.
- [HANDOVER.md](HANDOVER.md): short current-state handoff.
- [docs/SPEC.md](docs/SPEC.md): product and workflow contract.
- [docs/LLM.md](docs/LLM.md): typed model contracts.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): config, checks, import, backups, retention, and operations.
- [docs/OVERLAY_ANIMATION_PLAN.md](docs/OVERLAY_ANIMATION_PLAN.md): current overlay-animation MVP and next development steps.

`LOCAL.md` may exist locally with machine-specific deployment notes. It is git-ignored.

## Layout

```text
aimo.py                 CLI entrypoint
aimo.conf.example       config template
core/                   canonical events, config, routing, i18n, workflow contracts
app/                    dispatcher, runtime wiring, preflight, policy, redaction
adapters/discord/       Discord adapter, command registration, outgoing rendering
workflows/              chat, help, debug, GPX, workout management/chat, visualization
storage/                SQLite schema, migrations, repositories, import
workout/                GPX parsing, ingest, periods, workout reference resolution
visualization/          datasets, specs, renderers, animation overlays, tile fetching, service
llm/                    typed gateway, operations, OpenAI-compatible client
tests/                  unit and adapter tests
docs/                   durable project documentation
```

Do not use `legacy/` as implementation guidance unless explicitly doing import or comparison work.

## Common Commands

```bash
python3 aimo.py --check --config aimo.conf.example
python3 aimo.py --check-services --config aimo.conf.example
python3 aimo.py --preflight --config aimo.conf
python3 scripts/production_smoke.py --config aimo.conf --log logs/bot.log
python3 aimo.py --config aimo.conf --run-discord
```

Import documented JSON data:

```bash
python3 aimo.py --config aimo.conf --import-data export.json --dry-run
python3 aimo.py --config aimo.conf --import-data export.json
```

Before handoff, use the verification checklist in [docs/OPERATIONS.md](docs/OPERATIONS.md).
