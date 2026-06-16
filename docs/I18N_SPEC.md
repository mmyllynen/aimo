# Aimo Internationalization Spec

## Intent

Aimo is multilingual. Bot-owned deterministic user-facing messages must be localizable.

Supported languages:

- `fi`
- `en`

The active language is configured in `aimo.conf`; missing config defaults to Finnish. Explicit unsupported language codes must fail startup validation.

## Scope

Internationalization applies to:

- help text
- slash-command responses
- deterministic workflow responses
- error messages
- visualization captions
- GPX ingest summaries
- debug command framing text

LLM-generated prose must be instructed to answer in the configured language, but deterministic messages still come from the catalog.

## Translation Contract

Use stable translation keys:

```python
translator.text(TranslationKey.ERROR_NO_MATCHING_WORKOUT)
```

Avoid hard-coded deterministic user text in workflows/adapters.

Parameterized messages use named placeholders:

```python
translator.text(TranslationKey.ERROR_MISSING_METRIC, metric="heart_rate_bpm")
```

Each supported catalog must contain the same keys and the same placeholder names.

## Runtime Boundary

The runtime builds one `Translator` from config.

Workflows should return:

- translation keys plus parameters for deterministic messages
- localized text objects when composing through a controlled helper
- raw text only for validated LLM-generated prose or file captions that are explicitly composed by the workflow

The adapter/application boundary resolves translation keys before sending Discord messages.

## Acceptance

- config selects `fi` or `en`
- missing config defaults to `fi`
- invalid language fails clearly
- deterministic messages use translation keys
- catalogs validate key and placeholder parity
- tests cover config loading and catalog validation
