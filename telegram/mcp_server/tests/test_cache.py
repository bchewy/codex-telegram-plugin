from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from codex_telegram import cache
from codex_telegram.tools import cache as cache_tools


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _tool_from(name: str):
    mcp = _FakeMCP()
    cache_tools.register(mcp)
    return mcp.tools[name]


def _payload(message_id: int, *, day: int, text: str, sender_ref: str = "user:1", sender_name: str = "Alice") -> dict:
    return {
        "chat_ref": "chat:1",
        "id": message_id,
        "date": f"2026-04-{day:02d}T10:00:00+00:00",
        "sender_ref": sender_ref,
        "sender_name": sender_name,
        "text": text,
        "raw_text": text,
        "reply_to_message_id": None,
    }


def test_cache_schema_init_creates_tables():
    connection = cache.connect_cache(":memory:")
    try:
        cache.ensure_cache_schema(connection)
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {"schema_version", "messages", "messages_fts", "chat_sync_state"} <= tables


def test_cache_search_and_aggregate_workflows():
    connection = cache.connect_cache(":memory:")
    try:
        cache.ensure_cache_schema(connection)
        with connection:
            cache.upsert_cached_messages(
                connection,
                [
                    _payload(1, day=18, text="launch plan", sender_ref="user:1", sender_name="Alice"),
                    _payload(2, day=18, text="launch checklist", sender_ref="user:2", sender_name="Bob"),
                    _payload(3, day=19, text="post launch notes", sender_ref="user:1", sender_name="Alice"),
                ],
            )

        search_results = cache.search_cached_messages(
            connection,
            chat_ref="chat:1",
            query="launch",
            limit=10,
        )
        day_buckets = cache.aggregate_cached_messages(connection, chat_ref="chat:1", group_by="day")
        sender_buckets = cache.aggregate_cached_messages(connection, chat_ref="chat:1", group_by="sender")
    finally:
        connection.close()

    assert {item["id"] for item in search_results} == {1, 2, 3}
    assert day_buckets == [
        {"bucket": "2026-04-18", "count": 2},
        {"bucket": "2026-04-19", "count": 1},
    ]
    assert sender_buckets == [
        {"sender_ref": "user:1", "sender_name": "Alice", "count": 2},
        {"sender_ref": "user:2", "sender_name": "Bob", "count": 1},
    ]


def test_cached_message_chunk_paginates_without_loading_all_messages():
    connection = cache.connect_cache(":memory:")
    try:
        cache.ensure_cache_schema(connection)
        with connection:
            cache.upsert_cached_messages(
                connection,
                [
                    _payload(3, day=19, text="three"),
                    _payload(1, day=18, text="one"),
                    _payload(2, day=18, text="two"),
                    _payload(4, day=20, text="four"),
                ],
            )

        total = cache.count_cached_messages(connection, chat_ref="chat:1")
        chunk = cache.load_cached_message_chunk(
            connection,
            chat_ref="chat:1",
            limit=2,
            offset=1,
        )
    finally:
        connection.close()

    assert total == 4
    assert [item["id"] for item in chunk] == [2, 3]


def test_search_cached_messages_compact_results_include_snippet_and_pagination():
    connection = cache.connect_cache(":memory:")
    try:
        cache.ensure_cache_schema(connection)
        with connection:
            cache.upsert_cached_messages(
                connection,
                [
                    _payload(1, day=18, text="launch plan with a long enough surrounding sentence"),
                    _payload(2, day=19, text="launch checklist"),
                    _payload(3, day=20, text="unrelated"),
                ],
            )

        results = cache.search_cached_messages(
            connection,
            chat_ref="chat:1",
            query="launch",
            limit=1,
            offset=0,
            compact=True,
            text_limit=8,
        )
        next_results = cache.search_cached_messages(
            connection,
            chat_ref="chat:1",
            query="launch",
            limit=1,
            offset=1,
            compact=True,
        )
    finally:
        connection.close()

    assert len(results) == 1
    assert set(results[0]) == {
        "chat_ref",
        "id",
        "date",
        "sender_ref",
        "sender_name",
        "reply_to_message_id",
        "text",
        "snippet",
        "rank",
    }
    assert "[launch]" in results[0]["snippet"]
    assert results[0]["text"].endswith("…")
    assert len(next_results) == 1
    assert next_results[0]["id"] != results[0]["id"]


def test_search_cache_tool_defaults_to_full_payload_and_paginates(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "cache.db"
    connection = cache.connect_cache(db_path)
    try:
        cache.ensure_cache_schema(connection)
        with connection:
            cache.upsert_cached_messages(
                connection,
                [
                    _payload(1, day=18, text="launch one"),
                    _payload(2, day=19, text="launch two"),
                    _payload(3, day=20, text="launch three"),
                ],
            )
            cache.update_chat_sync_state(connection, "chat:1", 3)
    finally:
        connection.close()

    monkeypatch.setattr(cache_tools, "_canonical_chat_ref", lambda chat_ref: asyncio.sleep(0, result="chat:1"))
    monkeypatch.setattr(cache_tools, "_sender_ref", lambda from_user: asyncio.sleep(0, result=None))
    monkeypatch.setattr(cache_tools, "connect_cache", lambda: cache.connect_cache(db_path))

    first = asyncio.run(_tool_from("search_cache")(chat_ref="chat:1", query="launch", limit=2))
    second = asyncio.run(
        _tool_from("search_cache")(
            chat_ref="chat:1",
            query="launch",
            limit=2,
            offset=first["next_offset"],
            compact=True,
        )
    )

    assert first["compact"] is False
    assert first["count"] == 2
    assert first["has_more"] is True
    assert first["next_offset"] == 2
    assert "raw_text" in first["messages"][0]
    assert second["compact"] is True
    assert second["count"] == 1
    assert second["next_offset"] is None
    assert set(second["messages"][0]) == {
        "chat_ref",
        "id",
        "date",
        "sender_ref",
        "sender_name",
        "reply_to_message_id",
        "text",
        "snippet",
        "rank",
    }


def test_connect_cache_rejects_missing_sqlcipher(monkeypatch):
    monkeypatch.setenv(cache.CACHE_ENCRYPT_ENV_VAR, "1")
    monkeypatch.setattr(
        cache.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing sqlcipher")),
    )

    with pytest.raises(RuntimeError, match="pysqlcipher3"):
        cache.connect_cache(":memory:")


def test_sync_chat_cache_advances_delta_cursor(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "cache.db"
    fetch_calls: list[int] = []

    async def fake_fetch_bulk_history_payload(**kwargs):
        fetch_calls.append(kwargs["since_message_id"])
        if kwargs["since_message_id"] == 0:
            return {
                "chat_ref": "chat:1",
                "count": 2,
                "deleted_count": 0,
                "from_id": 1,
                "to_id": 2,
                "messages": [
                    _payload(1, day=18, text="one"),
                    _payload(2, day=18, text="two"),
                ],
                "truncated": False,
                "next_since_message_id": None,
                "used_takeout": False,
            }
        return {
            "chat_ref": "chat:1",
            "count": 1,
            "deleted_count": 0,
            "from_id": 3,
            "to_id": 3,
            "messages": [_payload(3, day=19, text="three")],
            "truncated": False,
            "next_since_message_id": None,
            "used_takeout": False,
        }

    monkeypatch.setattr(cache_tools, "fetch_bulk_history_payload", fake_fetch_bulk_history_payload)
    monkeypatch.setattr(cache_tools, "_canonical_chat_ref", lambda chat_ref: asyncio.sleep(0, result="chat:1"))
    monkeypatch.setattr(cache_tools, "connect_cache", lambda: cache.connect_cache(db_path))

    first = asyncio.run(_tool_from("sync_chat_cache")(chat_ref="chat:1"))
    second = asyncio.run(_tool_from("sync_chat_cache")(chat_ref="chat:1"))

    connection = cache.connect_cache(db_path)
    try:
        cache.ensure_cache_schema(connection)
        state = cache.get_chat_sync_state(connection, "chat:1")
        message_count = connection.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE chat_ref = ?",
            ("chat:1",),
        ).fetchone()["count"]
    finally:
        connection.close()

    assert first["max_cached_id"] == 2
    assert second["max_cached_id"] == 3
    assert fetch_calls == [0, 2]
    assert state is not None
    assert state["max_cached_id"] == 3
    assert message_count == 3
