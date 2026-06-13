# Aimo v3 Internationalization Spec

## Intent

Aimo is not a Finnish-only bot. All bot-owned user-facing messages must be localizable.

Initial supported languages:

- `fi`
- `en`

The active language is configured in `aimo.conf`.

```ini
[bot]
language = fi
```

If `aimo.conf` is missing or the setting is omitted, Aimo defaults to Finnish.

Unsupported language codes must fail clearly during startup/config validation. They must not silently fall back after an explicit invalid value.

## Scope

Internationalization applies to bot-owned text:

- help text
- slash-command responses
- deterministic workflow responses
- error messages
- visualization captions
- GPX ingest summaries
- debug command framing text

LLM-generated prose must also be instructed to answer in the configured language. The LLM is allowed to compose natural language, but the application must still localize deterministic messages through the translation catalog.

## Translation Contract

Application code should refer to stable translation keys, not hard-coded user-facing text.

Allowed pattern:

```python
translator.text(TranslationKey.ERROR_NO_MATCHING_WORKOUT)
```

Avoid:

```python
"En löytänyt pyynnölle sopivaa treeniä."
```

Parameterized messages must use named placeholders:

```python
translator.text(TranslationKey.ERROR_MISSING_METRIC, metric="heart_rate")
```

Every supported language catalog must contain the same keys and the same placeholder names for each key.

## Runtime Boundary

The Discord/runtime layer owns config loading and should construct one `Translator` from `aimo.conf`.

Workflows should return one of:

- already localized text, when the workflow owns a composed final response
- a translation key plus parameters, when the response is deterministic
- an error with a stable user-message key and parameters

The adapter or application service should resolve translation keys before sending Discord messages.

## LLM Language Rule

Every LLM request that can produce user-visible text must include the configured language as an explicit instruction.

Examples:

- `Respond in Finnish.`
- `Respond in English.`

Do not infer response language from the user's message unless a future product decision explicitly adds per-user or per-message language selection.

## Acceptance Criteria

Internationalization support is acceptable when:

- supported languages are defined as typed values
- `aimo.conf` can select `fi` or `en`
- missing config defaults to `fi`
- unsupported config values fail clearly
- deterministic user-facing messages use translation keys
- all catalogs are validated for key and placeholder parity
- tests cover config loading and catalog validation

