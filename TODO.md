# Aimo TODO

This is the short working backlog. Keep durable product rules in `docs/SPEC.md`, model contracts in `docs/LLM.md`, and operational procedures in `docs/OPERATIONS.md`.

## Current Focus

Aimo is production-capable. Recent work added deterministic workout rename/tag editing, production smoke tooling, social-image rendering with bounded style controls, route-map waypoints, kilometer markers, elevation overlays, deterministic help/privacy topics, and a bundle-based route/map/HR workout overlay-animation MVP.

Use this backlog for the next product, reliability, data-quality, and testability work. Avoid refactors that do not move one of those outcomes forward.

## Priority 1: User-Visible Features

- Add workout import/export commands for a user's own workout index and metadata.
- Add workout search/filter commands by tag, title, sport/type, date range, distance, and duration.
- Add workout notes and editable metadata beyond title/tags, such as private notes, activity type cleanup, and corrected date/time where safe.
- Add more natural non-route chart requests: monthly totals, weekly distance trend, HR-zone trends, latest-vs-previous comparison, and same-route comparison.
- Add GPX ingest support for multiple files in one request with one concise summary.
- Add social-image publish-oriented presets such as `+feed` and `+story`, plus richer stat/layout selections beyond the current classic/minimal/poster/route-only/data/photo styles.
- Continue overlay animation work from `docs/OVERLAY_ANIMATION_PLAN.md`: browser-preview/MP4 companion files for MOV overlays, HR-zone styling, lower-third/compact HR layouts, richer route-overview styling, and better YouTube-oriented presets.

## Priority 2: Reliability And Operations

- Add an operator health command or CLI report for process status, database path, migration version, configured guilds, and recent errors.
- Add retention jobs for debug traces, rendered artifacts, and old channel history according to config.
- Add backup/restore runbook and a tested SQLite backup command.
- Add a startup check that warns if `aimo.conf` contains `allow_direct_messages = true`, since runtime rejects DMs regardless.
- Add better failure logging around admin-DM delivery without exposing user content.
- Add metrics around LLM latency, model timeout, render failures, and GPX ingest failures.
- Design and implement staged storage encryption only after adding key-management and migration tests.

## Priority 3: Data And Model Quality

- Implement channel summary refresh so chat context does not rely only on recent raw history rows.
- Add user profile facts beyond HR zones where useful, with explicit privacy boundaries.
- Expand workout fact summaries for coaching while preserving the no-raw-points LLM rule.
- Move workout-chat workout reference interpretation fully behind the typed LLM selector contract; keep Python resolver limited to structured selector resolution.
- Improve the typed LLM selector/intent contracts for common Finnish/English workout and visualization requests without adding Python-side phrase parsers.
- Improve model fallback copy so unsupported or unavailable model states still give useful next steps.
- Add schema/version handling for visualization specs before introducing substantially richer chart capabilities.
- Add a typed LLM overlay-animation intent only after the deterministic `overlay=...` path is stable; keep model inputs to compact selectors and never raw GPX/point arrays.

## Priority 4: Code Health

- Split `app/dispatcher.py` into persistence, routing, tracing, and dispatch orchestration helpers once feature work touches it.
- Split `adapters/discord/runtime.py` into command registration, message handling, interaction handling, and admin notification helpers.
- Keep repository APIs narrow; add query helpers only when a workflow needs them.
- Review config fields that are now policy-disabled, especially `allow_direct_messages`, and decide whether to remove or keep as a rejected legacy field.
- Keep import hygiene tests strict so active code does not depend on `legacy/` or Discord objects outside adapters.
