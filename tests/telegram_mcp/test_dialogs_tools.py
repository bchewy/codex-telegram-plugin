from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from telethon import types

from codex_telegram.tools import dialogs


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _async_value(value):
    async def inner(*_args, **_kwargs):
        return value

    return inner


def _tool_from(name: str):
    mcp = _FakeMCP()
    dialogs.register(mcp)
    return mcp.tools[name]


class _DialogListClient:
    def __init__(self, titles: list[str]):
        self._titles = titles
        self.calls: list[dict] = []

    async def get_dialogs(self, limit=None, archived=None, ignore_pinned=False):
        self.calls.append(
            {"limit": limit, "archived": archived, "ignore_pinned": ignore_pinned}
        )
        items = self._titles if limit is None else self._titles[:limit]
        return [SimpleNamespace(title=title) for title in items]


def test_list_dialogs_filters_query_before_applying_limit(monkeypatch):
    # The match sits beyond the first `limit` dialogs; the old
    # fetch-limit-then-filter order silently missed it.
    titles = ["Alpha", "Beta", "Gamma", "Launch Crew", "Delta"]
    client = _DialogListClient(titles)
    monkeypatch.setattr(dialogs, "get_client", _async_value(client))
    monkeypatch.setattr(
        dialogs,
        "dialog_to_dict",
        lambda dialog: {"title": dialog.title, "display_name": dialog.title},
    )

    result = asyncio.run(_tool_from("list_dialogs")(limit=2, query="launch"))

    assert client.calls[0]["limit"] is None
    assert result["count"] == 1
    assert result["dialogs"][0]["title"] == "Launch Crew"


def test_list_dialogs_without_query_respects_limit(monkeypatch):
    client = _DialogListClient(["Alpha", "Beta", "Gamma"])
    monkeypatch.setattr(dialogs, "get_client", _async_value(client))
    monkeypatch.setattr(
        dialogs,
        "dialog_to_dict",
        lambda dialog: {"title": dialog.title, "display_name": dialog.title},
    )

    result = asyncio.run(_tool_from("list_dialogs")(limit=2))

    assert client.calls[0]["limit"] == 2
    assert result["count"] == 2


def test_list_dialogs_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="limit"):
        asyncio.run(_tool_from("list_dialogs")(limit=0))


class _PinClient:
    def __init__(self):
        self.requests = []

    async def __call__(self, request):
        self.requests.append(request)
        return SimpleNamespace()


def test_pin_dialog_returns_canonical_ref_and_invalidates_cache(monkeypatch):
    client = _PinClient()
    invalidated = []
    input_peer = types.InputPeerChannel(channel_id=42, access_hash=0)

    monkeypatch.setattr(dialogs, "get_client", _async_value(client))
    monkeypatch.setattr(dialogs, "resolve_input_peer", _async_value(input_peer))
    monkeypatch.setattr(
        dialogs, "invalidate_dialog_cache", lambda _client: invalidated.append(True)
    )

    result = asyncio.run(_tool_from("pin_dialog")(chat_ref="My Channel"))

    # The fuzzy caller string is normalized to the canonical peer ref.
    assert result == {"chat_ref": "channel:42", "pinned": True}
    assert invalidated == [True]


def test_mute_dialog_returns_canonical_ref(monkeypatch):
    client = _PinClient()
    input_peer = types.InputPeerUser(user_id=9, access_hash=0)

    monkeypatch.setattr(dialogs, "get_client", _async_value(client))
    monkeypatch.setattr(dialogs, "resolve_input_peer", _async_value(input_peer))

    result = asyncio.run(_tool_from("mute_dialog")(chat_ref="@someone"))

    assert result["chat_ref"] == "user:9"
    assert result["silent"] is True


def test_archive_dialog_invalidates_dialog_cache(monkeypatch):
    invalidated = []
    entity = types.PeerUser(user_id=5)
    client = SimpleNamespace(edit_folder=_async_value(None))

    monkeypatch.setattr(dialogs, "get_client", _async_value(client))
    monkeypatch.setattr(dialogs, "resolve_entity", _async_value(entity))
    monkeypatch.setattr(
        dialogs, "invalidate_dialog_cache", lambda _client: invalidated.append(True)
    )

    result = asyncio.run(_tool_from("archive_dialog")(chat_ref="user:5"))

    assert result == {"chat_ref": "user:5", "archived": True}
    assert invalidated == [True]
