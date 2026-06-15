# Aimo Handover

This is the fast entrypoint for the next session. The local tree under `/home/myllymik/Projects/aimo` is the standalone source of truth. Follow `AGENTS.md`: use local specs and code, do not use `legacy/` as implementation guidance unless explicitly asked for comparison/import work.

Current date/status: 2026-06-15. Aimo v3 is running in production on `mushroom` from `~/chatgpt`, which is the same physical tree visible through this local sshfs/fuse mount.

## Production State

- Runtime host: `mushroom`
- Runtime directory: `/home/myllymik/chatgpt`
- Runtime command: `python3 aimo.py --config aimo.conf --run-discord`
- Restart helper: `./check-restart.sh --force`
- Latest confirmed restart: 2026-06-15 12:16:49, log line `Aimo Discord runtime ready`
- Production preflight after latest changes: `Aimo production preflight OK: 7/7 checks passed`
- Discord smoke testing is in progress with the real bot.

Useful production commands:

```bash
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && source venv/bin/activate && python3 -m unittest discover"
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && source venv/bin/activate && python3 aimo.py --config aimo.conf --preflight"
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && ./check-restart.sh --force"
ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && tail -n 80 logs/bot.log"
```

## Verification Baseline

Last successful verification in this session:

```bash
source venv/bin/activate && python3 -m unittest discover
# Ran 195 tests OK

git diff --check
# OK

ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && source venv/bin/activate && python3 -m unittest tests.test_visualization_specs tests.test_visualization_workflow"
# Ran 49 tests OK

ssh -F ~/.ssh/config -o BatchMode=yes mushroom "cd ~/chatgpt && source venv/bin/activate && python3 aimo.py --config aimo.conf --preflight"
# 7/7 OK
```

A production dispatch probe for:

```text
@aimo piirrä viimeisimmästä treenistä sykealuejakauma
```

returned a PNG successfully before the latest restart.

## What Changed Today

### Discord Runtime

- Real Discord slash commands are registered through `discord.app_commands`.
- Slash interactions are deferred immediately with `thinking=True`, then answered via followup. This fixes Discord's 30 second initial interaction timeout without changing workflow logic.
- Startup logs now include command sync and ready state.
- Message processing and interaction processing log inbound/dispatch summaries.
- Interaction exceptions now send a generic localized error followup instead of leaving Discord stuck at "Aimo is thinking...".
- `allowed_mentions` dicts are converted to Discord `AllowedMentions`, fixing mention behavior.

### `/aimo`

- Removed the awkward `apua:true|false` boolean option.
- `/aimo` with no useful options returns help.
- `/aimo syote:<text>` remains generic text request.
- `/aimo liite:<file>` remains attachment ingest path.
- No compatibility layer was kept for `apua:true`.

### `/treenit`

- Workout listing format no longer exposes opaque `workout-<uuid>` ids by default.
- Listing now shows user-meaningful numbered rows with date, title, kind, distance, duration, and average HR when available.
- Users can refer to workouts by list number, date, title, latest, or active where supported.

### HR Zone Configuration

`/treenit toiminto:aseta_sykerajat zones:<value>` no longer accepts JSON as the intended path.

Accepted forms:

- `190`: max HR; derives five upper limits at 60/70/80/90/100%
- `114,133,152,171,190`: manual increasing upper limits for `pk1`, `pk2`, `vk1`, `vk2`, `mk`

Stored records use:

- `zone_key`: `z1..z5`
- labels: `pk1`, `pk2`, `vk1`, `vk2`, `mk`
- lower bounds derived as previous upper + 1

The production probe confirmed `zones=190` stored:

```text
z1 pk1 -114
z2 pk2 115-133
z3 vk1 134-152
z4 vk2 153-171
z5 mk 172-190
```

### Chat / LLM Robustness

- OpenAI structured output schemas were fixed for arrays.
- `chat_reply`, `workout_reply`, and visualization intent operations no longer fail because array `items` schemas are missing.
- Generic chat now receives capability/policy facts, so public mention requests like `@aimo listaa mun treenit` can be answered by the model with guidance to use private slash commands instead of Python adding hidden deterministic intent branches.
- `chat_reply` token budget was increased to avoid incomplete model responses.

### Attachment Routing

- Non-GPX attachments are rejected deterministically instead of falling through to chat/LLM.
- GPX attachments still route to GPX ingest.

### Visualization

The current visualization pipeline is generic and should stay that way:

```text
user text
-> VisualizationIntent
-> DatasetRequest
-> DatasetResolver
-> DatasetManifest
-> VisualizationSpec
-> validator/compiler
-> renderer adapter
-> PNG artifact
```

Current supported renderer marks are still `line` and `bar`.

Recent visualizer improvements:

- Multi-metric line charts default to small multiples when units differ.
- Explicit same-axis / scale requests can still normalize secondary series to the primary range.
- Charts now have better title/subtitle, labels, ticks, and a subtle background gradient.
- Dense rough line series can auto-smooth generically.
- Explicit smoothing via user text maps to rolling average.
- Outlier clipping is robust and less aggressive.
- Pace `s/km` is rendered as `min/km` and inverted so higher means faster visually.
- Bar charts can render duration ticks.
- HR zone distribution resolves through the generic `hr_zone_distribution` dataset, not a custom workflow branch.
- Category bar distributions no longer collapse into one aggregate metric bar when `aggregate_sum` appears.
- Spec compiler now prefers nominal/ordinal dataset axes when the requested x metric is also the y metric. This fixes LLM intents such as `x_metric=heart_rate_zone_seconds`, `y_metrics=(heart_rate_zone_seconds)`.

Tested manually:

- `@aimo piirrä viimeisimmästä treenistä syke ajan funktiona`
- `@aimo piirrä samaan kuvaajaan syke, vauhti ja korkeuskäyrä viimeisimmästä treenistä`
- `@aimo piirrä viimeisimmästä treenistä tasoitettu vauhtikäyrä ajan funktiona`
- `/treenit toiminto:aseta_sykerajat zones:190`
- `@aimo piirrä viimeisimmästä treenistä sykealuejakauma`

## Open Observations / Next Tests

Continue smoke testing from here.

Important current open visualization limitation:

- User asked: `@aimo tee sama piirakkakuviona, jakauma prosentuaalisesti`
- Actual result: same time-in-zone bar chart as before.
- Analysis: this is expected with current implementation because:
  - `arc`/pie/donut rendering is not implemented;
  - visualization follow-up context does not reliably carry "same" from the previous rendered chart;
  - there is no generic `as_percentage_of_total` / `normalize_to_share` transform yet.

Recommended next generic implementation direction:

- Add a generic percentage/share transform, e.g. `as_percentage_of_total`, valid for categorical bar datasets with numeric y values.
- Let LLM map words like `prosentuaalisesti`, `share`, `percentage`, `osuus`, `jakauma` to that transform, but Python must validate applicability.
- Render percentage bar charts first. Pie/donut can come later as a generic `arc` mark.
- If adding pie/donut, implement it as a renderer mark primitive, not a sykealue-specific branch.
- Add visualization follow-up context later so "tee sama" can refer to the previous visualization intent/spec/artifact.

Other good next smoke tests:

- `@aimo analysoi viimeisin treeni`
- `@aimo listaa mun treenit`
- `/aimo syote:mitä osaat tehdä?`
- Mention with a non-GPX image attachment
- GPX upload mention
- `/debug` after an intentional visualization/user error

## Current Design Guardrails

Python owns:

- state transitions
- data access
- owner checks
- validation
- transforms
- rendering
- localized deterministic user-facing errors

LLMs may:

- interpret user language into typed intent
- draft chat/workout replies from bounded facts

LLMs must not receive:

- raw GPX
- raw workout point rows
- secrets/config
- cross-user data

Avoid:

- Python hidden intent branches like `if user text says list workouts then do /treenit logic`
- visualization one-off product branches like `if HR zones then special render`
- compatibility layers unless explicitly requested
- deterministic user-facing text without i18n keys
- Discord.py objects outside the adapter boundary

## Dirty Worktree Note

The worktree is intentionally dirty from the production hardening/smoke-test session. Many files are modified and several files are new, including:

- `PROD_SMOKE_TEST.md`
- `check-restart.sh`
- `docs/DATA_IMPORT_SPEC.md`
- `storage/importer.py`
- `tests/test_data_import.py`

Do not revert unrelated changes. If committing later, inspect the full diff carefully and split if useful.

## Suggested Resume Order

1. Read `AGENTS.md`.
2. Read this `HANDOVER.md`.
3. Skim `PROD_SMOKE_TEST.md` for the full manual testing history.
4. Check `git status --short`.
5. If continuing visualizer work, read:
   - `docs/VISUALIZATION_SPEC.md`
   - `visualization/datasets.py`
   - `visualization/specs.py`
   - `visualization/service.py`
   - `visualization/render.py`
   - `tests/test_visualization_specs.py`
6. Before any production restart, run targeted tests, full tests if scope warrants it, `git diff --check`, and mushroom preflight.
