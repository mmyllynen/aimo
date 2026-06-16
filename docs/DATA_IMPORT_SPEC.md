# Aimo Data Import Spec

## Purpose

This document defines the one-way JSON import format for bringing exported user/runtime data into Aimo storage.

The importer is conservative:

- validates ownership before writing
- supports dry-run mode
- reports imported counts
- rejects conflicting primary keys
- does not delete source data
- does not copy, move, or mutate raw GPX files

## Format

Top-level JSON object:

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

`aimo.v3.import.v1` is the current stable import format id. Collections are optional lists. Unknown top-level keys are ignored.

## Collections

### users

Required:

- `user_id`
- either `first_seen_at` or `last_seen_at`

Optional:

- `discord_user_name`
- `discord_display_name`
- `last_seen_source`
- `metadata`

### channels

Required:

- `channel_id`

Optional:

- `guild_id`
- `channel_name`
- `metadata`

### channel_summaries

Required:

- `channel_id`
- `summary`
- `updated_at`

Optional:

- `turn_count`

The channel must exist in `channels`.

### heart_rate_zones

Required:

- `user_id`
- `zone_key`
- `label`

Optional:

- `lower_bpm`
- `upper_bpm`
- `sort_order`

The user must exist in `users`.

### history_events

Required:

- `history_id`
- `channel_id`
- `role`
- `event_type`
- `created_at`

Optional:

- `guild_id`
- `user_id`
- `content`
- `source_event_id`
- `metadata`

The channel must exist in `channels`. If `user_id` is present, the user must exist in `users`.

### attachments

Required:

- `attachment_id`
- `owner_user_id`
- `filename`
- `sha256`
- `raw_path`
- `created_at`

Optional:

- `guild_id`
- `channel_id`
- `message_id`
- `content_type`
- `size_bytes`
- `source_path`
- `metadata`

The owner must exist in `users`. If `channel_id` is present, the channel must exist in `channels`.

`raw_path` is stored as a reference only. `source_path` may be included for operator reporting, but the importer does not read or mutate it.

### workouts

Required:

- `workout_id`
- `owner_user_id`
- `title`
- `kind`
- `created_at`

Optional:

- `source_attachment_id`
- `guild_id`
- `channel_id`
- `primary_kind`
- `start_time_utc`
- `start_time_local`
- `local_date`
- `distance_km`
- `duration_s`
- `pace_s_per_km`
- `ascent_m`
- `avg_hr_bpm`
- `max_hr_bpm`
- `point_count`
- `schema_version`
- `tags`
- `metadata`

The owner must exist in `users`. If `source_attachment_id` is present, it must exist in `attachments` and belong to the same owner. If `channel_id` is present, the channel must exist in `channels`.

### active_workouts

Required:

- `user_id`
- `workout_id`
- `updated_at`

The workout must exist in `workouts` and belong to the same user.

## Running

Dry-run:

```bash
python3 aimo.py --config aimo.conf --import-data export.json --dry-run
```

Apply:

```bash
python3 aimo.py --config aimo.conf --import-data export.json
```

The importer opens the configured SQLite database and applies migrations before validation/import.
