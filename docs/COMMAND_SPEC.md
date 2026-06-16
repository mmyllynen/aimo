# Aimo Command Spec

## Surfaces

Aimo supports:

- public `@Aimo` mentions in allowed guild channels
- GPX attachments on supported mention/slash inputs
- `/aimo`
- `/treenit`
- `/debug`

Direct messages are rejected. Slash commands should be registered for configured allowed guilds when a guild allowlist exists.

## Mentions

Pattern:

```text
@Aimo <message>
```

Behavior:

- Normalize to a canonical mention event.
- Strip Aimo's own mention before workflow handling.
- Store inbound history.
- Route to help, chat, workout chat, GPX ingest, visualization, or debug as appropriate.
- Send a public response unless the workflow requires restricted output.
- Disable broad mentions in outgoing messages.

Normal non-mention guild messages may be persisted as history but must not produce a response.

## Attachments

Supported:

- `.gpx`
- common GPX/XML content types

Behavior:

- Attachment handling is deterministic.
- Invalid attachments produce stable localized errors.
- Multiple attachments should be processed independently when supported by the command surface.

## `/aimo`

Purpose: general Aimo command surface.

Parameters:

- `syote`: optional text request
- `liite`: optional GPX attachment

Behavior:

- No useful parameter: return help.
- `liite`: run GPX ingest.
- `syote`: route as a canonical user request.

## `/treenit`

Purpose: deterministic workout management.

Subcommands:

- `listaa`
- `nayta` with optional `viite`: workout id, list number, date, tag, kind, or title/search text
- `aktiivinen`
- `aseta_aktiivinen` with optional `viite`
- `poista` with optional `viite`
- `sykerajat`
- `aseta_sykerajat` with optional `zones`: max heart rate or five increasing BPM upper limits

Action rules:

- `listaa`: recent workouts for the current user with numbering, compact metrics, and a marker for the current workout when one is set.
- `nayta`: details for one resolved workout; the shown workout becomes the current workout context.
- `aktiivinen`: current active workout.
- `aseta_aktiivinen`: set active workout by reference.
- `poista`: first request creates a delete confirmation for one safely resolved user-owned workout; deletion happens only when the same user presses the confirm button within 60 seconds. The cancel button clears the pending delete.
- `sykerajat`: show current HR zones.
- `aseta_sykerajat`: update zones from one max-HR value or five increasing BPM upper limits.

Workout management replies should usually be ephemeral unless an explicit public mode is added later.

The current workout is primarily a background context, not a concept users must manage explicitly. The explicit active commands may remain available for deterministic control, but normal selection should happen through GPX ingest, `nayta`, or LLM-resolved workout references.

## `/debug`

Purpose: restricted trace export.

Parameters:

- optional mode selector (`tila`)

Behavior:

- Return latest relevant trace.
- Admin users may access broader traces.
- Output JSON artifact when large.
- Redact secrets and large raw payloads.
- Always restricted/ephemeral where Discord supports it.

## Error Responses

Command errors should be:

- short
- in the configured bot language
- specific enough to act on
- non-technical unless debug output is requested

Examples:

```text
En löytänyt tuolla viitteellä treeniä.
```

```text
Tuo liite ei näytä kelvolliselta GPX-tiedostolta.
```

```text
Treenistä puuttuu tarvittava mittari: heart_rate_bpm.
```
