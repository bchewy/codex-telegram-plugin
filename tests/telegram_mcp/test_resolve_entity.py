from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from codex_telegram.helpers import resolve_entity, resolve_entity_fuzzy


class _StrictErrorClient:
    async def get_entity(self, _candidate):
        raise RuntimeError("transport blew up")


class _FuzzyClient:
    def __init__(self, entity):
        self._entity = entity

    async def get_entity(self, _candidate):
        raise ValueError("not found")

    async def iter_dialogs(self):
        yield SimpleNamespace(title="Launch Chat", entity=self._entity)


class _NumericWarmClient:
    def __init__(self, entity):
        self._entity = entity
        self.calls = 0
        self.dialog_warmups = 0

    async def get_entity(self, _candidate):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("peer cache cold")
        return self._entity

    async def iter_dialogs(self):
        self.dialog_warmups += 1
        return
        yield  # unreachable; marks this as an async generator


def test_resolve_entity_propagates_transport_failures():
    with pytest.raises(RuntimeError, match="transport blew up"):
        asyncio.run(resolve_entity(_StrictErrorClient(), "launch"))


def test_resolve_entity_fuzzy_falls_back_to_dialog_title():
    entity = object()
    resolved = asyncio.run(resolve_entity_fuzzy(_FuzzyClient(entity), "launch chat"))

    assert resolved is entity


def test_resolve_entity_warms_dialog_cache_for_numeric_refs():
    entity = object()
    client = _NumericWarmClient(entity)

    resolved = asyncio.run(resolve_entity(client, "channel:123"))

    assert resolved is entity
    assert client.dialog_warmups == 1


class _NumericIdClient:
    def __init__(self, entity):
        self._entity = entity
        self.requested = []

    async def get_entity(self, candidate):
        self.requested.append(candidate)
        return self._entity


def test_resolve_entity_treats_bare_numeric_strings_as_ids():
    entity = object()
    client = _NumericIdClient(entity)

    resolved = asyncio.run(resolve_entity(client, "12345"))

    # Telethon parses numeric *strings* as phone numbers; the ref must be
    # converted to an int so it resolves as an entity id.
    assert resolved is entity
    assert client.requested == [12345]


def test_resolve_entity_fuzzy_rejects_blank_refs():
    entity = object()
    client = _FuzzyClient(entity)

    with pytest.raises(ValueError):
        asyncio.run(resolve_entity_fuzzy(client, "   "))


def test_resolve_input_user_wraps_wrong_kind_as_value_error(monkeypatch):
    from telethon import types

    from codex_telegram import helpers

    channel = types.Channel(
        id=10,
        title="Chan",
        photo=types.ChatPhotoEmpty(),
        date=None,
    )

    async def fake_resolve_entity(_client, _ref):
        return channel

    monkeypatch.setattr(helpers, "resolve_entity", fake_resolve_entity)

    with pytest.raises(ValueError, match="not a user reference"):
        asyncio.run(helpers.resolve_input_user(object(), "channel:10"))


def test_numeric_retry_invalidates_warm_dialog_cache():
    from codex_telegram.client import DIALOG_CACHE_ATTR
    import time

    entity = object()
    client = _NumericWarmClient(entity)
    # Pre-warm the memoized dialog list; without invalidation the retry
    # would skip the network fetch that actually warms Telethon's cache.
    setattr(client, DIALOG_CACHE_ATTR, (time.monotonic(), []))

    resolved = asyncio.run(resolve_entity(client, "chat:42"))

    assert resolved is entity
    assert client.dialog_warmups == 1
