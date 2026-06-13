# Aimo v3 Product Spec

## Product Definition

Aimo v3 is a multilingual Discord bot for conversation, workout tracking, GPX-based activity analysis, and workout visualization.

The bot serves one Discord community at a time but stores user-owned data. Aimo should feel like a practical assistant in the channel, not a dashboard or a generic chatbot.

## Product Goals

- Reply naturally and concisely to normal mentions.
- Act as a credible, concise workout coach when the topic is training.
- Accept GPX attachments and turn them into stored workouts.
- Let users manage workouts through deterministic slash commands.
- Let users ask for charts in natural language and receive rendered image files.
- Maintain enough history and profile context for follow-up messages.
- Provide debug traces for troubleshooting without exposing secrets or excessive data.

## Core User Workflows

### Normal Chat

User mentions Aimo with a normal conversational message.

Expected behavior:

- Aimo replies publicly in the channel.
- Reply language comes from `aimo.conf`; Finnish is the default when no language is configured.
- Reply is usually 1-4 sentences.
- The reply should not mention internal routing, JSON, prompts, models, or traces.
- The bot should keep follow-up context when recent channel history makes the reference clear.

### Workout Chat

User asks about training, workouts, pace, heart rate, route, recovery, or saved activity data.

Expected behavior:

- Aimo answers as a concise coach.
- If stored workout data is relevant, Aimo uses it.
- If stored data is missing, Aimo says so and can still give general guidance when appropriate.
- Aimo must not invent workout details.
- Follow-ups should keep workout context unless the user clearly changes topic.

### GPX Upload

User attaches one or more GPX files in a mention or supported slash command.

Expected behavior:

- Aimo validates each attachment.
- Valid GPX files are stored as user-owned workouts.
- Duplicate files are detected by content hash.
- Aimo replies with a compact summary of accepted and rejected files.
- Uploading a workout may update the user's active workout according to policy.

### Workout Management

User uses slash commands to manage saved workouts.

Expected behavior:

- Users can list workouts.
- Users can inspect a workout.
- Users can set active workout.
- Users can delete their own workout.
- Users can configure heart-rate zones.
- Commands are deterministic and do not require the LLM.

### Visualization

User asks Aimo to draw or visualize workout data.

Expected behavior:

- Aimo resolves the requested workout selection.
- Aimo builds a chart using available data.
- Aimo sends an image file and a short caption.
- Aimo does not ask which workout to use if the user explicitly says latest, active, or a specific workout.
- Missing data is handled with a precise note or error.

Example:

```text
@Aimo piirrä viimeisimmästä treenistä syke ajan funktiona, ja samaan kuvaajaan vauhti ja korkeus skaalattuna sykkeen alueelle
```

Expected result:

- Uses the latest eligible workout owned by the user.
- Draws heart rate against time or elapsed time.
- Adds pace and elevation as scaled overlay series if those metrics exist.
- If one overlay metric is missing, draws available data and notes the missing metric.
- Does not ask whether the user meant latest or a specific workout.

### Debug

User or admin invokes debug command.

Expected behavior:

- Aimo returns the latest relevant trace as a structured artifact.
- Debug output is ephemeral or otherwise restricted.
- Secrets and large raw payloads are redacted or summarized.

## Supported Languages And Tone

Initial supported languages:

- Finnish (`fi`)
- English (`en`)

The active language is configured in `aimo.conf` under `[bot] language`.

All deterministic bot-owned messages must use translation keys and catalogs. LLM-generated prose must be explicitly instructed to answer in the configured language.

Tone:

- concise
- direct
- helpful
- credible for training topics
- light playfulness is allowed when the user is playful

Workout tone:

- coach-like
- practical
- specific when data exists
- no exaggerated hype
- no invented certainty

## Public vs Ephemeral Behavior

Public channel replies:

- mention chat replies
- workout chat replies
- visualization captions and image files
- GPX ingest summaries when uploaded publicly

Ephemeral replies:

- debug output
- slash help where appropriate
- administrative status
- potentially destructive command confirmations

## Clarification Policy

Aimo should clarify only when it cannot proceed safely.

Do not clarify when:

- user says latest workout
- user says active workout
- user names a specific workout id/reference
- there is exactly one plausible candidate
- a best-effort answer can be produced with a clear note

Clarify when:

- multiple workouts match equally and the result would materially differ
- a destructive command needs confirmation
- requested data is impossible to identify
- permission is missing

## Data Ownership

- Workout data belongs to the Discord user who uploaded it.
- One user cannot access another user's workout data unless future explicit sharing support is added.
- Channel history belongs to the bot's operational context and should be bounded by retention policy.
- Debug traces are operational data and should be redacted.

## Feature Parity Acceptance

Aimo v3 is product-complete when:

- public mention chat works
- workout chat works
- GPX ingest works
- workout slash management works
- HR zone configuration works
- latest/active/specific workout references work
- natural-language visualizations produce images
- `/debug` returns useful traces
- all model calls are bounded and validated
- common failures produce stable localized user messages
