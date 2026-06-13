# Aimo v3 Workout Spec

## Workout Domain

A workout is a user-owned record derived from uploaded GPX data or future supported workout sources.

A workout can represent:

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

Only the owner can list, inspect, activate, delete, or visualize the workout.

## GPX Ingest

Input:

- GPX XML bytes
- attachment metadata
- uploader identity
- guild/channel/message metadata
- optional user HR zones

Validation:

- XML must parse.
- Root must be GPX-compatible.
- File must contain at least one useful track, route, or waypoint sequence.
- Size must be within configured limits.

Duplicate detection:

- SHA-256 hash of raw content.
- Same owner + same hash is duplicate.

## GPX Classification

Classify parsed GPX as:

- `activity`: has timestamped track points or sensor data indicating recorded activity
- `route_plan`: has route/track geometry but no activity timing/sensor data
- `hybrid`: contains both meaningful recorded activity and route plan data

Primary kind:

- `activity`
- `route`
- `hybrid`

## Canonical Workout Fields

Required:

- `workout_id`
- `owner_user_id`
- `title`
- `kind`
- `primary_kind`
- `created_at`
- `schema_version`

Optional derived fields:

- `start_time_utc`
- `start_time_local`
- `local_date`
- `distance_km`
- `duration_s`
- `pace_s_per_km`
- `ascent_m`
- `avg_hr_bpm`
- `max_hr_bpm`
- `avg_cadence_spm`
- `max_cadence_spm`
- `point_count`
- `tags`

## Point Fields

Workout points may include:

- `point_index`
- `segment_index`
- `timestamp_utc`
- `elapsed_s`
- `distance_m`
- `distance_km`
- `latitude`
- `longitude`
- `elevation_m`
- `heart_rate_bpm`
- `cadence_spm`
- `pace_s_per_km`

Point streams must remain in storage and deterministic services. They must not be sent wholesale to routing or planning LLM calls.

## Streams

Supported stream keys:

- `heart_rate`
- `cadence`
- `pace`
- `elevation`
- `distance`

Stream summary should include:

- unit
- sample count
- min
- max
- average where meaningful

## Heart-Rate Zones

User HR zones are ordered named BPM ranges.

Default labels may include:

- `pk1`
- `pk2`
- `vk1`
- `vk2`
- `mk`

The exact zone labels are user-configurable. Derived zone distribution should be calculated from HR samples when zones exist.

Zone derivation output:

- zone key
- label
- seconds
- share
- lower/upper BPM

## Workout References

Supported user references:

- exact workout id
- active workout
- latest workout
- list index from recent list
- date
- date range
- tag
- workout type/kind
- title fragment

Resolution policy:

- exact id wins
- active/latest are explicit selectors
- one clear match resolves
- ambiguous matches clarify
- no match returns `no_matching_workout`

## Latest Workout Policy

"Latest workout" means the newest user-owned workout by workout start time when available, otherwise upload/create time.

If the latest workout lacks a requested metric:

- do not ask whether the user meant another workout
- either produce a best-effort result with available metrics and a note
- or return a specific missing metric message

## Active Workout Policy

Each user can have one active workout.

Set active when:

- user explicitly sets it
- GPX ingest policy chooses to make latest upload active

Active workout is a user convenience pointer, not a permission boundary.

## Workout Summary Text

Compact workout summaries should include, when available:

- title
- local date/time
- distance
- duration
- pace
- average/max HR
- tags

Keep summaries short enough for Discord lists.

## Data Missing Policy

Do not invent:

- HR
- pace
- duration
- elevation
- splits
- route details

When missing:

- say the metric is missing
- offer useful alternative if possible
- avoid broad clarification unless workflow truly cannot proceed

