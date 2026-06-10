from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from codex_telegram.tools import extras
from codex_telegram.tools.extras import _draft_items


def test_draft_items_accepts_list_none_and_singleton():
    sentinel = object()
    assert _draft_items([1, 2]) == [1, 2]
    assert _draft_items(None) == []
    assert _draft_items(sentinel) == [sentinel]


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


def test_vote_poll_rejects_out_of_range_indices(monkeypatch):
    mcp = _FakeMCP()
    extras.register(mcp)
    vote_poll = mcp.tools["vote_poll"]

    poll_message = SimpleNamespace(
        media=SimpleNamespace(
            poll=SimpleNamespace(
                answers=[
                    SimpleNamespace(option=b"0"),
                    SimpleNamespace(option=b"1"),
                ]
            )
        )
    )
    client = SimpleNamespace(get_messages=_async_value(poll_message))
    monkeypatch.setattr(extras, "get_client", _async_value(client))
    monkeypatch.setattr(extras, "resolve_entity", _async_value(SimpleNamespace()))
    monkeypatch.setattr(extras, "resolve_input_peer", _async_value(SimpleNamespace()))

    with pytest.raises(ValueError, match="option index"):
        asyncio.run(vote_poll(chat_ref="chat:1", message_id=1, option_indices=[2]))
