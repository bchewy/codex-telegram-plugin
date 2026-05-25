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


class _SearchClient:
    def __init__(self, messages_to_yield):
        self.messages_to_yield = messages_to_yield
        self.calls = []

    async def __call__(self, request):
        self.calls.append(
            {
                "request_type": type(request).__name__,
                "search": request.q,
                "min_date": request.min_date,
                "max_date": request.max_date,
                "offset_id": request.offset_id,
                "offset_peer": request.offset_peer,
                "offset_rate": request.offset_rate,
                "limit": request.limit,
            }
        )
        for item in self.messages_to_yield:
            if request.max_date and item.date >= request.max_date:
                continue
            if request.min_date and item.date < request.min_date:
                continue
            if request.offset_id and item.id >= request.offset_id:
                continue
            return SimpleNamespace(messages=[item], users=[], chats=[], next_rate=len(self.calls))
        return SimpleNamespace(messages=[], users=[], chats=[], next_rate=0)

    async def iter_messages(
        self,
        entity,
        search: str,
        from_user=None,
        offset_date=None,
        offset_id: int = 0,
        limit: int = 1000,
    ):
        self.calls.append(
            {
                "entity": entity,
                "search": search,
                "from_user": from_user,
                "offset_date": offset_date,
                "offset_id": offset_id,
                "limit": limit,
            }
        )
        count = 0
        for item in self.messages_to_yield:
            if offset_date and item.date >= offset_date:
                continue
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

    async def iter_dialogs(self):
        yield self._dialog

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
        self.iter_calls: list[dict] = []
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

    async def iter_messages(self, _entity, limit: int | None = None, offset_id: int | None = None):
        self.iter_calls.append({"limit": limit, "offset_id": offset_id})
        upper = (offset_id - 1) if offset_id else self.highest_id
        count = 0
        for mid in range(upper, 0, -1):
            if limit and count >= limit:
                break
            if mid in self.empty_ids:
                yield _EmptyMessage(id=mid)
            else:
                yield SimpleNamespace(id=mid)
            count += 1


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


def test_search_in_chat_pages_past_newer_out_of_window_matches(monkeypatch):
    entity = SimpleNamespace()
    search_messages = [
        SimpleNamespace(id=10, date=datetime(2026, 4, 10, tzinfo=UTC)),
        SimpleNamespace(id=9, date=datetime(2026, 4, 9, tzinfo=UTC)),
        SimpleNamespace(id=8, date=datetime(2026, 4, 8, tzinfo=UTC)),
        SimpleNamespace(id=4, date=datetime(2026, 4, 4, tzinfo=UTC)),
        SimpleNamespace(id=3, date=datetime(2026, 4, 3, tzinfo=UTC)),
        SimpleNamespace(id=2, date=datetime(2026, 4, 2, tzinfo=UTC)),
    ]
    client = _SearchClient(search_messages)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(entity))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])
    monkeypatch.setattr(messages, "peer_ref", lambda _entity: "chat:1")

    result = asyncio.run(
        _tool_from("search_messages_in_chat")(
            chat_ref="chat:1",
            query="launch",
            limit=2,
            min_date="2026-04-03T00:00:00Z",
            max_date="2026-04-04T23:59:59Z",
        )
    )

    assert result["count"] == 2
    assert result["messages"] == [{"id": 4}, {"id": 3}]
    assert result["scanned_count"] == 3
    assert client.calls[0]["search"] == "launch"
    assert client.calls[0]["offset_date"] == datetime(2026, 4, 4, 23, 59, 59, 1, tzinfo=UTC)


def test_search_global_reports_more_results_without_overfetching_payload(monkeypatch):
    search_messages = [
        SimpleNamespace(id=5, date=datetime(2026, 4, 5, tzinfo=UTC)),
        SimpleNamespace(id=4, date=datetime(2026, 4, 4, tzinfo=UTC)),
        SimpleNamespace(id=3, date=datetime(2026, 4, 3, tzinfo=UTC)),
    ]
    client = _SearchClient(search_messages)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])

    result = asyncio.run(_tool_from("search_messages_global")(query="launch", limit=2))

    assert result["count"] == 2
    assert result["messages"] == [{"id": 5}, {"id": 4}]
    assert result["has_more"] is True
    assert result["scanned_count"] == 3
    assert client.calls[0]["request_type"] == "SearchGlobalRequest"


def test_search_global_does_not_report_more_when_page_exactly_exhausts(monkeypatch):
    search_messages = [
        SimpleNamespace(id=5, date=datetime(2026, 4, 5, tzinfo=UTC)),
        SimpleNamespace(id=4, date=datetime(2026, 4, 4, tzinfo=UTC)),
    ]
    client = _SearchClient(search_messages)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])

    result = asyncio.run(_tool_from("search_messages_global")(query="launch", limit=2))

    assert result["count"] == 2
    assert result["has_more"] is False
    assert result["next_offset"] is None
    assert result["messages"] == [{"id": 5}, {"id": 4}]


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


def test_bulk_fetch_history_forward_walk_filters_empty_messages_and_fetches_concurrently(monkeypatch):
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

    # since_message_id=1 forces the incremental forward-walk path so we can
    # exercise concurrent chunk fetches via _fetch_message_chunk.
    result = asyncio.run(
        messages.fetch_bulk_history_payload(
            chat_ref="chat:1",
            since_message_id=1,
            max_messages=500,
            concurrency=4,
        )
    )

    # Walks ids 2..205 (204 ids), 3 empty -> 201 payloads.
    assert result["count"] == 201
    assert result["deleted_count"] == 3
    assert result["from_id"] == 2
    assert result["to_id"] == 205
    assert result["truncated"] is False
    assert client.max_concurrent > 1
    # Forward-walk path uses get_messages chunks, not iter_messages.
    assert client.iter_calls == []


def test_bulk_fetch_history_forward_walk_returns_truncation_cursor(monkeypatch):
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
            since_message_id=1,
            max_messages=120,
            concurrency=3,
        )
    )

    # Walks 2..250 in chunks of 100: [2..101], [102..201], [202..250].
    # All three fetch concurrently; processing stops once 120 payloads collected.
    assert result["count"] == 120
    assert result["truncated"] is True
    assert result["next_since_message_id"] == 121


def test_bulk_fetch_history_forward_walk_advances_raw_ids_when_all_messages_empty(monkeypatch):
    client = _BulkClient(5, empty_ids={2, 3, 4, 5})

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
            since_message_id=1,
            max_messages=10,
        )
    )

    assert result["count"] == 0
    assert result["deleted_count"] == 4
    assert result["from_id"] == 2
    assert result["to_id"] == 5
    assert result["oldest_fetched_id"] == 2


def test_bulk_fetch_history_forward_walk_retries_one_chunk_after_flood_wait(monkeypatch):
    # Forward walk from since=1 to highest=100 produces a single chunk [2..100].
    client = _BulkClient(100, flood_chunk=tuple(range(2, 101)))

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

    result = asyncio.run(
        messages.fetch_bulk_history_payload(chat_ref="chat:1", since_message_id=1)
    )

    assert result["count"] == 99
    assert client.calls.count(tuple(range(2, 101))) == 2


def test_bulk_fetch_history_bootstrap_walks_newest_first_via_iter_messages(monkeypatch):
    # With since_message_id=0 (first sync), bootstrap must skip the id-range
    # walk and use Telethon's offset-based iter_messages instead — otherwise
    # chats whose lowest used id is hundreds of thousands deep (Saved
    # Messages) blow the 90s MCP tool timeout walking empty IDs.
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
            max_messages=50,
        )
    )

    # Bootstrap yields ids 205,204,...,156 (50 newest). None of them are in
    # empty_ids={5,6,150}, so all 50 land as payloads, sorted ascending.
    assert result["count"] == 50
    assert result["from_id"] == 156
    assert result["to_id"] == 205
    assert result["truncated"] is False
    assert result["next_since_message_id"] is None
    # Hit the message cap with more messages below id 156 — must signal
    # incompleteness so the caller doesn't treat the cache as exhaustive.
    assert result["older_history_uncached"] is True
    assert result["oldest_fetched_id"] == 156
    # Bootstrap uses iter_messages, not get_messages chunks.
    assert client.calls == []
    assert client.iter_calls == [{"limit": 50, "offset_id": None}]


def test_bulk_fetch_history_bootstrap_reports_complete_when_chat_smaller_than_limit(monkeypatch):
    client = _BulkClient(8)

    @asynccontextmanager
    async def fake_history_client(**_kwargs):
        yield client

    monkeypatch.setattr(messages, "get_client", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "get_history_client", fake_history_client)
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages.types, "MessageEmpty", _EmptyMessage)

    # max_messages=100 with only 8 messages available → did NOT hit the cap.
    result = asyncio.run(
        messages.fetch_bulk_history_payload(chat_ref="chat:1", max_messages=100)
    )
    assert result["count"] == 8
    assert result["older_history_uncached"] is False
    assert result["oldest_fetched_id"] == 1


def test_bulk_fetch_history_bootstrap_advances_raw_ids_when_all_messages_empty(monkeypatch):
    client = _BulkClient(5, empty_ids={1, 2, 3, 4, 5})

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
            max_messages=5,
        )
    )

    assert result["count"] == 0
    assert result["deleted_count"] == 5
    assert result["from_id"] == 1
    assert result["to_id"] == 5
    assert result["oldest_fetched_id"] == 1
    assert result["older_history_uncached"] is True


def test_bulk_fetch_history_bootstrap_flags_incomplete_when_iterator_hits_cap_with_filtered_messages(monkeypatch):
    # Regression: prior heuristic used `len(payloads) >= max_messages` AFTER
    # filtering empty/deleted messages — so a chat with empty-message tombstones
    # in the newest slice would report `older_history_uncached=False` even when
    # iter_messages was capped by `limit`. Track raw yields instead.
    client = _BulkClient(50, empty_ids={50, 49, 48})  # 3 of 50 newest are empty

    @asynccontextmanager
    async def fake_history_client(**_kwargs):
        yield client

    monkeypatch.setattr(messages, "get_client", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "get_history_client", fake_history_client)
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(SimpleNamespace()))
    monkeypatch.setattr(messages, "peer_ref", lambda entity: "chat:1")
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages.types, "MessageEmpty", _EmptyMessage)

    # max_messages=10 yields 10 raw items; 3 may be in empty_ids on a different
    # range, but at limit=10 we get the newest 10 (ids 50..41) — 3 are empty,
    # 7 land as payloads. Raw count == 10 == cap → older_history_uncached.
    result = asyncio.run(
        messages.fetch_bulk_history_payload(chat_ref="chat:1", max_messages=10)
    )
    assert result["count"] == 7
    assert result["deleted_count"] == 3
    # Before the fix: len(payloads)=7 < 10 → would have flagged False (BUG).
    # After the fix: raw_count=10 >= 10 → correctly True.
    assert result["older_history_uncached"] is True


def test_bulk_fetch_history_bootstrap_honors_until_message_id(monkeypatch):
    client = _BulkClient(500)

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
            until_message_id=100,
            max_messages=10,
        )
    )

    # offset_id=101 (exclusive) so iter_messages yields 100,99,...,91 = 10 ids
    # (none in empty_ids), sorted ascending.
    assert result["count"] == 10
    assert result["from_id"] == 91
    assert result["to_id"] == 100
    assert result["truncated"] is False
    assert result["next_since_message_id"] is None
    # Hit the cap (10 == max_messages=10) → flag incomplete.
    assert result["older_history_uncached"] is True
    assert result["oldest_fetched_id"] == 91
    assert client.iter_calls == [{"limit": 10, "offset_id": 101}]


def test_search_in_chat_returns_next_offset_when_more_results_pending(monkeypatch):
    entity = SimpleNamespace()
    search_messages = [
        SimpleNamespace(id=10, date=datetime(2026, 4, 10, tzinfo=UTC)),
        SimpleNamespace(id=9, date=datetime(2026, 4, 9, tzinfo=UTC)),
        SimpleNamespace(id=8, date=datetime(2026, 4, 8, tzinfo=UTC)),
    ]
    monkeypatch.setattr(messages, "get_client", _async_value(_SearchClient(search_messages)))
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(entity))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])
    monkeypatch.setattr(messages, "peer_ref", lambda _entity: "chat:1")

    result = asyncio.run(
        _tool_from("search_messages_in_chat")(
            chat_ref="chat:1",
            query="launch",
            limit=2,
        )
    )

    assert result["has_more"] is True
    assert result["scan_limit_reached"] is False
    assert result["next_offset"] == {"date": "2026-04-08T00:00:00+00:00", "id": 9}


def test_search_global_returns_next_offset_when_scan_limit_reached(monkeypatch):
    search_messages = [
        SimpleNamespace(id=20, date=datetime(2026, 4, 20, tzinfo=UTC)),
        SimpleNamespace(id=19, date=datetime(2026, 4, 19, tzinfo=UTC)),
        SimpleNamespace(id=18, date=datetime(2026, 4, 18, tzinfo=UTC)),
        SimpleNamespace(id=17, date=datetime(2026, 4, 17, tzinfo=UTC)),
    ]
    client = _SearchClient(search_messages)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])

    result = asyncio.run(
        _tool_from("search_messages_global")(
            query="launch",
            limit=10,
            scan_limit=2,
        )
    )

    assert result["count"] == 2
    assert result["has_more"] is False
    assert result["scan_limit_reached"] is True
    assert result["next_offset"] == {
        "date": "2026-04-19T00:00:00+00:00",
        "id": 19,
        "offset_peer": None,
        "offset_rate": 2,
    }


def test_search_global_resume_uses_peer_and_rate_cursor(monkeypatch):
    peer = messages.types.InputPeerChannel(123, 456)
    search_messages = [
        SimpleNamespace(
            id=20,
            date=datetime(2026, 4, 20, tzinfo=UTC),
            input_chat=peer,
            peer_id=messages.types.PeerChannel(123),
        ),
        SimpleNamespace(
            id=19,
            date=datetime(2026, 4, 19, tzinfo=UTC),
            input_chat=messages.types.InputPeerChannel(456, 789),
            peer_id=messages.types.PeerChannel(456),
        ),
    ]
    client = _SearchClient(search_messages)
    resolved_peer = object()
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "resolve_input_peer", _async_value(resolved_peer))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])

    first = asyncio.run(_tool_from("search_messages_global")(query="launch", limit=1))
    assert first["next_offset"] == {
        "date": "2026-04-20T00:00:00+00:00",
        "id": 20,
        "offset_peer": "channel:123",
        "offset_rate": 1,
    }

    resume_start = len(client.calls)
    asyncio.run(
        _tool_from("search_messages_global")(
            query="launch",
            limit=1,
            offset_id=first["next_offset"]["id"],
            offset_peer=first["next_offset"]["offset_peer"],
            offset_rate=first["next_offset"]["offset_rate"],
        )
    )

    assert client.calls[resume_start]["offset_peer"] is resolved_peer
    assert client.calls[resume_start]["offset_rate"] == 1


def test_search_in_chat_resumes_cleanly_when_offset_id_passed_back(monkeypatch):
    entity = SimpleNamespace()
    # Three messages share the same timestamp — the cursor must rely on id.
    same_day = datetime(2026, 4, 8, 12, 0, 0, tzinfo=UTC)
    search_messages = [
        SimpleNamespace(id=12, date=same_day),
        SimpleNamespace(id=11, date=same_day),
        SimpleNamespace(id=10, date=same_day),
        SimpleNamespace(id=9, date=same_day),
    ]
    client = _SearchClient(search_messages)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "resolve_entity_fuzzy", _async_value(entity))
    monkeypatch.setattr(messages, "iter_message_dicts", lambda items: [{"id": item.id} for item in items])
    monkeypatch.setattr(messages, "peer_ref", lambda _entity: "chat:1")

    first = asyncio.run(
        _tool_from("search_messages_in_chat")(
            chat_ref="chat:1",
            query="launch",
            limit=2,
        )
    )
    assert [m["id"] for m in first["messages"]] == [12, 11]
    assert first["next_offset"] is not None

    second = asyncio.run(
        _tool_from("search_messages_in_chat")(
            chat_ref="chat:1",
            query="launch",
            limit=2,
            offset_id=first["next_offset"]["id"],
        )
    )
    assert [m["id"] for m in second["messages"]] == [10, 9]
    # The boundary message (id=10) is not duplicated; ids are disjoint.
    first_ids = {m["id"] for m in first["messages"]}
    second_ids = {m["id"] for m in second["messages"]}
    assert first_ids.isdisjoint(second_ids)


class _UnreadFanoutClient:
    def __init__(self, *, per_dialog_messages, error_for_entity_id: int | None = None, error: Exception | None = None):
        self._per_dialog_messages = per_dialog_messages
        self._error_for_entity_id = error_for_entity_id
        self._error = error
        self.in_flight = 0
        self.max_concurrent = 0
        self.fetched_entities: list = []

    async def get_messages(self, entity, limit: int, min_id: int):
        self.in_flight += 1
        self.max_concurrent = max(self.max_concurrent, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            self.fetched_entities.append(entity)
            if self._error and id(entity) == self._error_for_entity_id:
                raise self._error
            return self._per_dialog_messages.get(id(entity), [])[:limit]
        finally:
            self.in_flight -= 1


def test_get_unread_global_mode_returns_partial_results_when_one_dialog_errors(monkeypatch):
    # Healthy dialogs A and C, plus dialog B that raises a generic per-dialog
    # error (e.g. ChannelPrivateError on a kicked channel). With the partial-
    # results fix, healthy dialogs still deliver messages and the failure is
    # reported in `errors`.
    entity_a = SimpleNamespace()
    entity_b = SimpleNamespace()
    entity_c = SimpleNamespace()
    dialog_a = SimpleNamespace(entity=entity_a, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=10))
    dialog_b = SimpleNamespace(entity=entity_b, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=20))
    dialog_c = SimpleNamespace(entity=entity_c, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=30))
    per_dialog = {
        id(entity_a): [SimpleNamespace(id=11, out=False), SimpleNamespace(id=12, out=False)],
        id(entity_c): [SimpleNamespace(id=31, out=False), SimpleNamespace(id=32, out=False)],
    }

    class _ChannelPrivateError(Exception):
        pass

    client = _UnreadFanoutClient(
        per_dialog_messages=per_dialog,
        error_for_entity_id=id(entity_b),
        error=_ChannelPrivateError("CHANNEL_PRIVATE: kicked"),
    )

    async def fake_list_all_dialogs(_client):
        return [dialog_a, dialog_b, dialog_c]

    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "list_all_dialogs", fake_list_all_dialogs)
    monkeypatch.setattr(messages, "dialog_to_dict", lambda d: {"entity_id": id(d.entity)})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages, "peer_ref", lambda entity: f"entity_{id(entity)}")

    result = asyncio.run(_tool_from("get_unread")(limit=10))

    # Healthy dialogs A and C delivered their messages despite B's failure.
    returned_ids = sorted(m["id"] for m in result["messages"])
    assert returned_ids == [11, 12, 31, 32]
    assert result["dialog_count"] == 2  # A and C in results, B is in errors
    # B's failure is surfaced structurally instead of crashing the call.
    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert err["error_type"] == "_ChannelPrivateError"
    assert "CHANNEL_PRIVATE" in err["error"]
    assert err["chat_ref"] == f"entity_{id(entity_b)}"


def test_get_unread_global_mode_propagates_cancellation_instead_of_swallowing(monkeypatch):
    # asyncio.CancelledError inherits directly from BaseException in 3.8+ —
    # if we catch BaseException as a per-dialog error we'd silently swallow
    # cancellation (MCP tool timeout, client disconnect, etc.). Must let
    # non-Exception BaseException subclasses propagate.
    entity_a = SimpleNamespace()
    entity_b = SimpleNamespace()
    dialog_a = SimpleNamespace(entity=entity_a, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=10))
    dialog_b = SimpleNamespace(entity=entity_b, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=20))
    client = _UnreadFanoutClient(
        per_dialog_messages={
            id(entity_a): [SimpleNamespace(id=11, out=False), SimpleNamespace(id=12, out=False)],
        },
        error_for_entity_id=id(entity_b),
        error=asyncio.CancelledError("simulated cancellation"),
    )

    async def fake_list_all_dialogs(_client):
        return [dialog_a, dialog_b]

    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "list_all_dialogs", fake_list_all_dialogs)
    monkeypatch.setattr(messages, "dialog_to_dict", lambda d: {"entity_id": id(d.entity)})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages, "peer_ref", lambda entity: f"entity_{id(entity)}")

    import pytest

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_tool_from("get_unread")(limit=10))


def test_get_unread_global_mode_propagates_flood_wait_error(monkeypatch):
    # FloodWaitError on one dialog must propagate so the outer with_flood_wait
    # decorator can decide whether to retry or surface the backoff. Swallowing
    # it as a per-dialog error would hide rate-limiting from the caller.
    entity_a = SimpleNamespace()
    dialog_a = SimpleNamespace(entity=entity_a, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=10))

    class _ScopedFloodWait(Exception):
        def __init__(self, seconds):
            super().__init__(f"wait {seconds}")
            self.seconds = seconds

    client = _UnreadFanoutClient(
        per_dialog_messages={},
        error_for_entity_id=id(entity_a),
        error=_ScopedFloodWait(15),
    )

    async def fake_list_all_dialogs(_client):
        return [dialog_a]

    monkeypatch.setattr(messages.errors, "FloodWaitError", _ScopedFloodWait)
    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "list_all_dialogs", fake_list_all_dialogs)
    monkeypatch.setattr(messages, "dialog_to_dict", lambda d: {"entity_id": id(d.entity)})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})
    monkeypatch.setattr(messages, "peer_ref", lambda entity: f"entity_{id(entity)}")
    monkeypatch.setattr(messages.asyncio, "sleep", _async_value(None))

    # `with_flood_wait` on get_unread will catch the first FloodWait, sleep,
    # and retry once. The retry hits the same error again, which now exceeds
    # the retry budget and is wrapped as TelegramFloodWaitError.
    import pytest
    from codex_telegram.client import TelegramFloodWaitError

    with pytest.raises(TelegramFloodWaitError) as captured:
        asyncio.run(_tool_from("get_unread")(limit=10))

    assert captured.value.seconds == 15
    assert captured.value.tool_name == "get_unread"


def test_get_unread_global_mode_recovers_from_unread_count_undershoot(monkeypatch):
    # Dialogs a and b each REPORT unread_count=3 (cumulative 6, matches the
    # global limit) but each actually returns 2 real unread messages — so the
    # first parallel round under-fetches (4 messages, not 6). A second round
    # must query dialog c to make up the shortfall.
    entity_a = SimpleNamespace()
    entity_b = SimpleNamespace()
    entity_c = SimpleNamespace()
    dialog_a = SimpleNamespace(entity=entity_a, unread_count=3, dialog=SimpleNamespace(read_inbox_max_id=10))
    dialog_b = SimpleNamespace(entity=entity_b, unread_count=3, dialog=SimpleNamespace(read_inbox_max_id=20))
    dialog_c = SimpleNamespace(entity=entity_c, unread_count=5, dialog=SimpleNamespace(read_inbox_max_id=30))
    per_dialog = {
        id(entity_a): [SimpleNamespace(id=11, out=False), SimpleNamespace(id=12, out=False)],
        id(entity_b): [SimpleNamespace(id=21, out=False), SimpleNamespace(id=22, out=False)],
        id(entity_c): [
            SimpleNamespace(id=31, out=False),
            SimpleNamespace(id=32, out=False),
            SimpleNamespace(id=33, out=False),
        ],
    }
    client = _UnreadFanoutClient(per_dialog_messages=per_dialog)

    async def fake_list_all_dialogs(_client):
        return [dialog_a, dialog_b, dialog_c]

    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "list_all_dialogs", fake_list_all_dialogs)
    monkeypatch.setattr(messages, "dialog_to_dict", lambda d: {"entity_id": id(d.entity)})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})

    result = asyncio.run(_tool_from("get_unread")(limit=6))

    assert len(result["messages"]) == 6
    returned_ids = sorted(m["id"] for m in result["messages"])
    assert returned_ids == [11, 12, 21, 22, 31, 32]
    # Round 1 queries a+b; under-fetches by 2; round 2 queries c.
    assert client.fetched_entities == [entity_a, entity_b, entity_c]


def test_get_unread_global_mode_fetches_dialogs_concurrently(monkeypatch):
    entity_a = SimpleNamespace()
    entity_b = SimpleNamespace()
    entity_c = SimpleNamespace()
    dialog_a = SimpleNamespace(entity=entity_a, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=10))
    dialog_b = SimpleNamespace(entity=entity_b, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=20))
    dialog_c = SimpleNamespace(entity=entity_c, unread_count=2, dialog=SimpleNamespace(read_inbox_max_id=30))
    per_dialog = {
        id(entity_a): [SimpleNamespace(id=11, out=False), SimpleNamespace(id=12, out=False)],
        id(entity_b): [SimpleNamespace(id=21, out=False), SimpleNamespace(id=22, out=False)],
        id(entity_c): [SimpleNamespace(id=31, out=False), SimpleNamespace(id=32, out=False)],
    }
    client = _UnreadFanoutClient(per_dialog_messages=per_dialog)

    async def fake_list_all_dialogs(_client):
        return [dialog_a, dialog_b, dialog_c]

    monkeypatch.setattr(messages, "get_client", _async_value(client))
    monkeypatch.setattr(messages, "list_all_dialogs", fake_list_all_dialogs)
    monkeypatch.setattr(messages, "dialog_to_dict", lambda d: {"entity_id": id(d.entity)})
    monkeypatch.setattr(messages, "message_to_dict", lambda message: {"id": message.id})

    result = asyncio.run(_tool_from("get_unread")(limit=6))

    assert result["dialog_count"] == 3
    assert client.max_concurrent >= 2
    returned_ids = sorted(m["id"] for m in result["messages"])
    assert returned_ids == [11, 12, 21, 22, 31, 32]
