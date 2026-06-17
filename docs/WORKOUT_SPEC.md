# Aimo Workout Spec

## Domain

A workout is a user-owned record derived from uploaded GPX data or future supported workout sources.

Workout kinds:

- recorded activity
- route plan
- hybrid activity/route source

## Ownership

Every workout has:

- `workout_id`
- `owner_user_id`
- source guild/channel/message when available
- created timestamp
- schema version

Only the owner can list, inspect, activate, delete, chat about, or visualize the workout.

## GPX Ingest

Input:

- GPX XML bytes
- attachment metadata
- uploader identity
- guild/channel/message metadata

Validation:

- XML parses.
- Root is GPX-compatible.
- File contains useful track, route, or waypoint data.
- Size is within configured limits.

Duplicate detection:

- SHA-256 of raw content.
- Duplicate key is same owner plus same hash.

## Canonical Fields

Required:

- `workout_id`
- `owner_user_id`
- `title`
- `kind`
- `primary_kind`
- `created_at`
- `schema_version`

Optional derived fields:

- start time UTC/local
- local date
- distance
- duration
- pace
- ascent
- average/max HR
- cadence
- point count
- tags/metadata

## Points And Streams

Point fields may include:

- timestamp/elapsed time
- distance
- latitude/longitude
- elevation
- heart rate
- cadence
- pace
- segment index

Supported stream summaries:

- heart rate
- cadence
- pace
- elevation
- distance

Point rows and raw GPX remain in deterministic services/storage. They must not be sent wholesale to routing or planning LLM calls.

## Heart-Rate Zones

User HR zones are ordered BPM ranges.

Default labels may include:

- `pk1`
- `pk2`
- `vk1`
- `vk2`
- `mk`

Zone distribution output:

- zone key/label
- seconds
- share
- lower/upper BPM

## Workout References

Aimo keeps a current workout context per user. This is internal workflow state used to make follow-up requests natural; users should not need to manage it explicitly in normal use.

Current workout updates:

- GPX ingest sets the imported workout as current.
- `/treenit nayta` sets the shown workout as current.
- `/treenit nimea`, `/treenit tagaa`, and `/treenit poista_tagi` update only safely resolved user-owned workouts and set the edited workout as current.
- Workout chat and visualization may set the resolved workout as current only when the LLM returns the explicit structured context-update flag and the selector resolves to exactly one user-owned workout.
- Ambiguous, missing, general, or comparison requests must not update current workout.

Python must not infer current-workout updates from natural-language substrings. It may only resolve structured selectors and execute explicit context-update fields returned by LLM contracts or deterministic slash-command choices.

Supported references:

- exact workout id
- active workout
- latest workout
- list index from recent list
- date
- date range
- tag
- workout kind/type
- title fragment

Resolution policy:

- exact id wins
- active/latest are explicit selectors
- one clear match resolves
- ambiguous matches clarify
- no match returns `no_matching_workout`

Latest workout means newest user-owned workout by start time when available, otherwise create/upload time.

## Missing Data

Do not invent:

- HR
- pace
- duration
- elevation
- splits
- route details

When data is missing:

- say which metric is missing
- produce best effort when secondary data is missing
- avoid clarification when the selected workout is explicit
