from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
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

    async def iter_messages(
        self,
        _entity,
        limit: int = 100,
        offset_id: int = 0,
        offset_date=None,
        reverse: bool = False,
        from_user=None,
    ):
        count = 0
        items = list(reversed(self.history)) if reverse else list(self.history)
        for item in items:
            if offset_id and item.id >= offset_id:
                continue
            if offset_date:
                if reverse and item.date <= offset_date:
                    continue
                if not reverse and item.date >= offset_date:
                    continue
            if from_user is not None:
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


class _ContextClient:
    def __init__(self, history):
        self.history = history

    async def get_messages(self, _entity, limit: int | None = None, max_id: int | None = None, min_id: int | None = None, reverse: bool = False, ids: int | None = None):
        if ids is not None:
            return next((item for item in self.history if item.id == ids), None)
        if max_id is not None:
            return [item for item in self.history if item.id < max_id][:limit]
        if min_id is not None:
            return [item for item in reversed(self.history) if item.id > min_id][:limit]
        return self.history[:limit]


class _EmptyMessage:
    def __init__(self, id: int):
        self.id = id


class _FakeFloodWaitError(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"wait {seconds}")
        self.seconds = seconds


class _BulkClient:
    def __init__(self, highest_id: int, *, empty_ids: set[int] | None = None, flood_chunk: tuple[int, ...] | None = None):
        self.highest_id = highest_id
        self.empty_ids = empty_ids or set()
        self.flood_chunk = flood_chunk
        self.flooded = False
        self.calls: list[tuple[int, ...]] = []
        self.in_flight = 0
        self.max_concurrent = 0

    async def get_messages(self, _entity, limit: int | None = None, ids: list[int] | None = None):
        if ids is None:
            assert limit == 1
            return [SimpleNamespace(id=self.highest_id)]

        chunk = tuple(ids)
        self.calls.append(chunk)
        self.in_flight += 1
        self.max_concurrent = max(self.max_concurrent, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            if self.flood_chunk == chunk and not self.flooded:
                self.flooded = True
                raise messages.errors.FloodWaitError(1)
            return [
                _EmptyMessage(id=item_id) if item_id in self.empty_ids else SimpleNamespace(id=item_id)
                for item_id in ids
            ]
        finally:
            self.in_flight -= 1


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


def test_get_history_walks_forward_from_min_date(monkeypatch):
    history = [
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
            min_date="2026-04-03T00:00:00Z",
        )
    )

    assert result["count"] == 2
    assert result["messages"] == [{"id": 3}, {"id": 4}]


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


def test_get_message_context_returns_surrounding_messages(monkeypatch):
    history = [
        SimpleNamespace(id=4),
        SimpleNamespace(id=3),
        SimpleNamespace(id=2),
        SimpleNamespace(id=1),
    ]
    monkeypatch.setattr(messages, "get_client", _async_value(_ContextClient(history)))
    monkeypatch.setattr(messages, "resolve_entity", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")

    result = asyncio.run(
        _tool_from("get_message_context")(chat_ref="chat:1", message_id=3, context_size=1)
    )

    assert result["count"] == 3
    assert result["messages"] == [{"id": 2}, {"id": 3}, {"id": 4}]


def test_bulk_fetch_history_filters_empty_messages_and_fetches_concurrently(monkeypatch):
    client = _BulkClient(205, empty_ids={5, 6, 150})

    @asynccontextmanager
    async def fake_history_client(**_kwargs):
        yield client

    monkeypatch.setattr(messages, "get_client", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "get_history_client", fake_history_client)
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages.types, "MessageEmpty", _EmptyMessage)

    result = asyncio.run(
        messages.fetch_bulk_history_payload(
            chat_ref="chat:1",
            max_messages=500,
            concurrency=4,
        )
    )

    assert result["count"] == 202
    assert result["deleted_count"] == 3
    assert result["from_id"] == 1
    assert result["to_id"] == 205
    assert result["truncated"] is False
    assert client.max_concurrent > 1


def test_bulk_fetch_history_returns_truncation_cursor(monkeypatch):
    client = _BulkClient(250)

    @asynccontextmanager
    async def fake_history_client(**_kwargs):
        yield client

    monkeypatch.setattr(messages, "get_client", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "get_history_client", fake_history_client)
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages.types, "MessageEmpty", _EmptyMessage)

    result = asyncio.run(
        messages.fetch_bulk_history_payload(
            chat_ref="chat:1",
            max_messages=120,
            concurrency=3,
        )
    )

    assert result["count"] == 120
    assert result["truncated"] is True
    assert result["next_since_message_id"] == 120


def test_bulk_fetch_history_retries_one_chunk_after_flood_wait(monkeypatch):
    client = _BulkClient(100, flood_chunk=tuple(range(1, 101)))

    @asynccontextmanager
    async def fake_history_client(**_kwargs):
        yield client

    monkeypatch.setattr(messages, "get_client", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "get_history_client", fake_history_client)
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages.types, "MessageEmpty", _EmptyMessage)
    monkeypatch.setattr(messages.errors, "FloodWaitError", _FakeFloodWaitError)
    monkeypatch.setattr(messages.asyncio, "sleep", _async_value(None))

    result = asyncio.run(messages.fetch_bulk_history_payload(chat_ref="chat:1"))

    assert result["count"] == 100
    assert client.calls.count(tuple(range(1, 101))) == 2
