# Aimo Product Spec

## Definition

Aimo is a multilingual Discord bot for channel conversation, workout coaching, GPX-based workout storage, workout management, and natural-language workout visualizations.

Aimo should feel like a practical assistant in the channel: concise, useful, and dependable. It may use an LLM for language interpretation and prose, but deterministic application code owns state changes, validation, storage, rendering, permissions, and error handling.

## Goals

- Reply naturally and concisely to `@Aimo` mentions.
- Store GPX uploads as user-owned workouts.
- Let users manage workouts through deterministic slash commands.
- Answer workout questions from bounded, validated workout facts.
- Render workout charts from natural-language requests.
- Maintain bounded channel history and user profile context.
- Provide structured debug traces without exposing secrets or raw data.

## Discord Policy

- Direct messages are rejected.
- Guild and optional channel allowlists are enforced before dispatch.
- The bot responds only to mentions and slash commands.
- Normal guild messages may be stored as history and produce no response.
- A user can be passively observed in history before their first active interaction.
- Admin users receive a DM on the first accepted mention/slash interaction from a user.

## Core Workflows

### Chat

User mentions Aimo with a general message.

Expected behavior:

- Public channel reply.
- Configured language from `aimo.conf`.
- Usually 1-4 sentences.
- No mention of internal routing, JSON, prompts, model details, or traces.
- Uses bounded recent context when it helps.

### Workout Chat

User asks about training, workouts, pace, heart rate, route, recovery, or saved workout data.

Expected behavior:

- Concise coach-like answer.
- Uses stored workout facts when relevant.
- States clearly when data is missing.
- Does not invent workout details.
- Keeps follow-up context when recent channel history makes it clear.

### GPX Upload

User attaches GPX through a supported mention or slash command.

Expected behavior:

- Validate size/type/content.
- Store valid GPX as a user-owned workout.
- Detect duplicate uploads by owner and content hash.
- Store raw GPX under configured storage root.
- Return a compact accepted/rejected summary.

### Workout Management

User manages saved workouts with `/treenit`.

Expected behavior:

- List recent workouts.
- Show one workout.
- Show or set active workout.
- Delete a user-owned workout.
- Show or update heart-rate zones.
- Avoid LLM dependency.

### Visualization

User asks for a chart in natural language.

Expected behavior:

- Resolve the requested user-owned workout or workout collection.
- Build a validated visualization spec.
- Render a PNG artifact.
- Send the image with a short caption.
- Handle missing metrics precisely.
- Never send raw workout point rows to the model for planning.

### Debug

User or admin invokes `/debug`.

Expected behavior:

- Return the latest relevant trace as a restricted JSON artifact.
- Non-admins see only traces relevant to themselves.
- Admin users may access broader traces.
- Secrets and large payloads are redacted or summarized.

## Language And Tone

Supported languages:

- Finnish (`fi`)
- English (`en`)

The active language is configured in `aimo.conf` under `[bot] language`; Finnish is the default.

Deterministic bot-owned messages must use translation keys. LLM-generated prose must be instructed to answer in the configured language.

Tone:

- concise
- direct
- helpful
- credible for training topics
- no exaggerated certainty

## Privacy And Ownership

- Workout data belongs to the Discord user who uploaded it.
- Users cannot access another user's workouts unless explicit sharing is added later.
- Channel history is operational context and must be bounded by retention policy.
- Debug traces are operational data and must be redacted.
- Raw GPX and full point streams stay in deterministic storage/services, not model planning inputs.

## Clarification Policy

Clarify only when the bot cannot proceed safely or usefully.

Do not clarify when:

- the user says latest workout
- the user says active workout
- the user gives a specific id/date/list reference
- exactly one plausible candidate exists
- a best-effort result can be produced with a clear missing-data note

Clarify when:

- multiple workouts match equally and the result would materially differ
- a destructive command is ambiguous
- requested data cannot be identified
- permission is missing
