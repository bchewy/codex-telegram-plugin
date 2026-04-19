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

    async def get_dialogs(self, limit: int = 200):
        assert limit == 200
        return [SimpleNamespace(title="Launch Chat", entity=self._entity)]


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

    async def get_dialogs(self, limit: int = 200):
        assert limit == 200
        self.dialog_warmups += 1
        return []


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
