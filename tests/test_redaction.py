from __future__ import annotations

import unittest

from app.redaction import REDACTED, TRUNCATED, RedactionPolicy, redact_payload


class RedactionTests(unittest.TestCase):
    def test_redacts_sensitive_keys_recursively(self) -> None:
        payload = {
            "token": "abc",
            "nested": {
                "api_key": "secret",
                "safe": "visible",
            },
        }

        redacted = redact_payload(payload)

        self.assertEqual(redacted["token"], REDACTED)
        self.assertEqual(redacted["nested"]["api_key"], REDACTED)
        self.assertEqual(redacted["nested"]["safe"], "visible")

    def test_truncates_large_strings_and_sequences(self) -> None:
        policy = RedactionPolicy(max_string_length=5, max_sequence_items=2)

        redacted = redact_payload(
            {
                "long": "abcdefghij",
                "items": [1, 2, 3],
            },
            policy,
        )

        self.assertEqual(redacted["long"], f"abcde...{TRUNCATED}")
        self.assertEqual(redacted["items"], [1, 2, f"{TRUNCATED}: 1 more items"])

