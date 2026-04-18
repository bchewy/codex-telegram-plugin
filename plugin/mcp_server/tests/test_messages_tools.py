from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

from codex_telegram.tools import messages


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
    messages.register(mcp)
    return mcp.tools[name]


class _HistoryClient:
    def __init__(self, history):
        self.history = history

    async def iter_messages(self, _entity, limit: int = 100, offset_id: int = 0, from_user=None):
        count = 0
        for item in self.history:
            if offset_id and item.id >= offset_id:
                continue
            yield item
            count += 1
            if limit and count >= limit:
                break


class _UnreadClient:
    def __init__(self, dialog, unread_messages):
        self._dialog = dialog
        self._unread_messages = unread_messages

    async def get_dialogs(self, limit: int = 200):
        assert limit == 200
        return [self._dialog]

    async def get_messages(self, _entity, limit: int, min_id: int):
        assert min_id == 10
        return self._unread_messages[:limit]


def test_get_history_keeps_paging_until_it_finds_in_range_messages(monkeypatch):
    history = [
        SimpleNamespace(id=10, date=datetime(2026, 4, 10, tzinfo=UTC)),
        SimpleNamespace(id=9, date=datetime(2026, 4, 9, tzinfo=UTC)),
        SimpleNamespace(id=8, date=datetime(2026, 4, 8, tzinfo=UTC)),
        SimpleNamespace(id=7, date=datetime(2026, 4, 7, tzinfo=UTC)),
        SimpleNamespace(id=6, date=datetime(2026, 4, 6, tzinfo=UTC)),
        SimpleNamespace(id=5, date=datetime(2026, 4, 5, tzinfo=UTC)),
        SimpleNamespace(id=4, date=datetime(2026, 4, 4, tzinfo=UTC)),
        SimpleNamespace(id=3, date=datetime(2026, 4, 3, tzinfo=UTC)),
        SimpleNamespace(id=2, date=datetime(2026, 4, 2, tzinfo=UTC)),
        SimpleNamespace(id=1, date=datetime(2026, 4, 1, tzinfo=UTC)),
    ]
    monkeypatch.setattr(messages, "get_client", _async_value(_HistoryClient(history)))
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")

    result = asyncio.run(
        _tool_from("get_history")(
            chat_ref="chat:1",
            limit=2,
            max_date="2026-04-04T23:59:59Z",
        )
    )

    assert result["count"] == 2
    assert result["messages"] == [{"id": 4}, {"id": 3}]


def test_get_unread_returns_flat_messages_list_for_global_mode(monkeypatch):
    dialog = SimpleNamespace(
        entity=SimpleNamespace(),
        unread_count=2,
        dialog=SimpleNamespace(read_inbox_max_id=10),
    )
    unread_messages = [
        SimpleNamespace(id=11, out=False),
        SimpleNamespace(id=12, out=False),
    ]
    monkeypatch.setattr(messages, "get_client", _async_value(_UnreadClient(dialog, unread_messages)))
    monkeypatch.setattr(messages, "dialog_to_dict", lambda dialog_obj: {"chat_ref": "chat:1"})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})

    result = asyncio.run(_tool_from("get_unread")(limit=10))

    assert result["dialog_count"] == 1
    assert result["messages"] == [{"id": 11}, {"id": 12}]
    assert result["results"][0]["messages"] == [{"id": 11}, {"id": 12}]
