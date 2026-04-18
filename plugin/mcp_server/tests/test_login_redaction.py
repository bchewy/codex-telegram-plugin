from __future__ import annotations

from codex_telegram.__main__ import _redact_phone


def test_redact_phone_masks_middle_digits():
    assert _redact_phone("+15555555555") == "+15*******55"


def test_redact_phone_preserves_short_values():
    assert _redact_phone(None) is None
    assert _redact_phone("1234") == "1234"
