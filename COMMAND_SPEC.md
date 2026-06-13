# Aimo v3 Command Spec

## Command Surfaces

Aimo supports:

- public mentions
- GPX attachments on supported inputs
- `/aimo`
- `/treenit`
- `/debug`

All slash commands must be deterministic unless they explicitly forward text to a workflow that uses the LLM.

## Mentions

Pattern:

```text
@Aimo <message>
```

Behavior:

- Normalize to a canonical mention event.
- Store inbound history.
- Route to chat, workout chat, GPX ingest, visualization, help, or debug as appropriate.
- Send public response unless workflow requires ephemeral output.

Mention safety:

- Strip Aimo's own mention from text before workflow handling.
- Disable broad mentions in outgoing messages.

## Attachments

Supported:

- `.gpx`
- GPX XML content with common GPX content types

Behavior:

- Attachment handling is deterministic.
- Invalid attachments produce a stable error summary.
- Multiple attachments are processed independently.

## `/aimo`

Purpose: general Aimo command surface.

Parameters:

- `apua`: boolean, optional
- `liite`: attachment, optional
- `syote`: string, optional

Behavior:

- If `apua` is true, return help text.
- If `liite` is present, run GPX ingest for that attachment.
- If `syote` is present, route it as a canonical user request.
- If no useful parameter is present, return help text.

Visibility:

- Help may be ephemeral.
- Routed text may be public or ephemeral depending on adapter mode.
- Attachment ingest response follows command visibility policy.

## `/treenit`

Purpose: deterministic workout management.

Parameter:

- `toiminto`: one of the supported actions
- optional `viite`: workout id, list number, date, tag, or search reference
- optional HR zone fields for zone configuration

Supported actions:

- `listaa`
- `nayta`
- `aktiivinen`
- `aseta_aktiivinen`
- `poista`
- `sykerajat`
- `aseta_sykerajat`

Action behavior:

### `listaa`

Returns recent workouts for the current user.

### `nayta`

Shows details for one workout resolved by `viite`.

### `aktiivinen`

Shows the active workout.

### `aseta_aktiivinen`

Sets active workout by `viite`.

### `poista`

Deletes a user-owned workout by exact id or safely resolved reference.

Deletion policy:

- If ambiguous, clarify.
- If exact and command semantics are explicit, delete.
- If future UI supports confirmation, prefer confirmation for destructive actions.

### `sykerajat`

Shows current HR zones.

### `aseta_sykerajat`

Updates HR zones from explicit numeric limits.

Validation:

- Zone limits must be increasing.
- Values must be plausible positive BPM values.

Visibility:

- Workout management slash replies should usually be ephemeral unless a public mode is explicitly requested later.

## `/debug`

Purpose: return structured trace information.

Parameters:

- optional `tila` or mode selector

Behavior:

- Return latest trace relevant to the user/channel.
- Admin users may access broader traces if configured.
- Output is an attached JSON artifact when large.
- Secrets and large raw data must be redacted.

Visibility:

- Always ephemeral or restricted.

## Help Text Requirements

Help text must explain:

- how to mention Aimo
- how to upload GPX
- how to list/manage workouts
- how to ask for visualizations
- that Aimo stores operational user/workout/history data
- that answers and visualizations are best-effort

## Error Response Requirements

Command errors should be:

- short
- Finnish
- specific
- non-technical unless debug mode is requested

Examples:

```text
En löytänyt tuolla viitteellä treeniä.
```

```text
Tuo liite ei näytä kelvolliselta GPX-tiedostolta.
```

```text
Viimeisimmässä treenissä ei ole sykedataa, joten en voi piirtää sykekäyrää siitä.
```

