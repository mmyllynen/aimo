PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    discord_user_name TEXT NOT NULL DEFAULT '',
    discord_display_name TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_seen_source TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS heart_rate_zones (
    user_id TEXT NOT NULL,
    zone_key TEXT NOT NULL,
    label TEXT NOT NULL,
    lower_bpm INTEGER,
    upper_bpm INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, zone_key),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS guild_policies (
    guild_id TEXT NOT NULL,
    policy_key TEXT NOT NULL,
    policy_value TEXT NOT NULL,
    PRIMARY KEY (guild_id, policy_key)
);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    guild_id TEXT,
    channel_name TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS channel_summaries (
    channel_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    turn_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS history_events (
    history_id TEXT PRIMARY KEY,
    guild_id TEXT,
    channel_id TEXT NOT NULL,
    user_id TEXT,
    role TEXT NOT NULL,
    event_type TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    source_event_id TEXT,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_history_channel_created
    ON history_events(channel_id, created_at);

CREATE TABLE IF NOT EXISTS attachments (
    attachment_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    guild_id TEXT,
    channel_id TEXT,
    message_id TEXT,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER,
    sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workouts (
    workout_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    source_attachment_id TEXT,
    guild_id TEXT,
    channel_id TEXT,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    primary_kind TEXT NOT NULL DEFAULT '',
    start_time_utc TEXT,
    start_time_local TEXT,
    local_date TEXT,
    distance_km REAL,
    duration_s REAL,
    pace_s_per_km REAL,
    ascent_m REAL,
    avg_hr_bpm REAL,
    max_hr_bpm REAL,
    point_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (source_attachment_id) REFERENCES attachments(attachment_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_workouts_owner_start
    ON workouts(owner_user_id, start_time_local DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS active_workouts (
    user_id TEXT PRIMARY KEY,
    workout_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (workout_id) REFERENCES workouts(workout_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workout_tags (
    workout_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (workout_id, tag),
    FOREIGN KEY (workout_id) REFERENCES workouts(workout_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workout_points (
    workout_id TEXT NOT NULL,
    point_index INTEGER NOT NULL,
    timestamp_utc TEXT,
    elapsed_s REAL,
    distance_m REAL,
    distance_km REAL,
    latitude REAL,
    longitude REAL,
    elevation_m REAL,
    heart_rate_bpm REAL,
    cadence_spm REAL,
    pace_s_per_km REAL,
    segment_index INTEGER,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (workout_id, point_index),
    FOREIGN KEY (workout_id) REFERENCES workouts(workout_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workout_streams (
    workout_id TEXT NOT NULL,
    stream_key TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT '',
    sample_count INTEGER NOT NULL DEFAULT 0,
    min_value REAL,
    max_value REAL,
    avg_value REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (workout_id, stream_key),
    FOREIGN KEY (workout_id) REFERENCES workouts(workout_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS debug_traces (
    trace_id TEXT PRIMARY KEY,
    source_event_id TEXT,
    workflow TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS debug_trace_events (
    trace_event_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (trace_id) REFERENCES debug_traces(trace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rendered_artifacts (
    artifact_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workflow_trace_id TEXT,
    artifact_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    storage_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
