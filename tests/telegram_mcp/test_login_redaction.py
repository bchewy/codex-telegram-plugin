from __future__ import annotations

from codex_telegram.__main__ import _redact_phone


def test_redact_phone_masks_middle_digits():
    assert _redact_phone("+15555555555") == "+15*******55"


def test_redact_phone_masks_short_values_entirely():
    assert _redact_phone(None) is None
    # Values too short to keep a meaningful prefix/suffix are fully masked
    # rather than printed in cleartext.
    assert _redact_phone("1234") == "****"
    assert _redact_phone("12345") == "*****"
