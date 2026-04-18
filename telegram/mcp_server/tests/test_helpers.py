from __future__ import annotations

from datetime import UTC
from types import SimpleNamespace

from telethon import types

from codex_telegram import helpers
from codex_telegram.helpers import coerce_message_ids, parse_datetime, peer_ref, user_to_dict


def test_parse_datetime_normalizes_to_utc():
    parsed = parse_datetime("2026-04-18T12:34:56+02:00")
    assert parsed is not None
    assert parsed.tzinfo == UTC
    assert parsed.hour == 10


def test_parse_datetime_accepts_z_suffix():
    parsed = parse_datetime("2026-04-18T12:34:56Z")
    assert parsed is not None
    assert parsed.tzinfo == UTC
    assert parsed.hour == 12


def test_coerce_message_ids_accepts_scalar_and_sequence():
    assert coerce_message_ids(7) == [7]
    assert coerce_message_ids([1, 2, 3]) == [1, 2, 3]


def test_peer_ref_formats_known_peer_types():
    assert peer_ref(types.PeerUser(user_id=1)) == "user:1"
    assert peer_ref(types.PeerChat(chat_id=2)) == "chat:2"
    assert peer_ref(types.PeerChannel(channel_id=3)) == "channel:3"


def test_user_to_dict_redacts_phone(monkeypatch):
    entity = SimpleNamespace(
        id=42,
        username="alice",
        phone="+15555555555",
        bot=False,
        verified=True,
        premium=False,
    )
    monkeypatch.setattr(helpers, "peer_ref", lambda user: f"user:{user.id}")
    monkeypatch.setattr(helpers.tg_utils, "get_display_name", lambda user: "Alice")

    payload = user_to_dict(entity)

    assert payload["user_ref"] == "user:42"
    assert payload["display_name"] == "Alice"
    assert payload["has_phone"] is True
    assert "phone" not in payload
