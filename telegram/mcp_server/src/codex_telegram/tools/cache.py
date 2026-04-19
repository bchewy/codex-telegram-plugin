from __future__ import annotations

from datetime import UTC, datetime
import math

from ..cache import (
    aggregate_cached_messages,
    cache_status as build_cache_status,
    clear_chat_cache,
    connect_cache,
    ensure_cache_schema,
    get_chat_sync_state,
    load_cached_messages,
    search_cached_messages,
    update_chat_sync_state,
    upsert_cached_messages,
)
from ..client import get_client
from ..helpers import peer_ref, resolve_entity_fuzzy
from .messages import fetch_bulk_history_payload


async def _canonical_chat_ref(chat_ref: str) -> str:
    client = await get_client()
    entity = await resolve_entity_fuzzy(client, chat_ref)
    return peer_ref(entity)


async def _sender_ref(from_user: str | None) -> str | None:
    if not from_user:
        return None
    client = await get_client()
    entity = await resolve_entity_fuzzy(client, from_user)
    return peer_ref(entity)


def register(mcp) -> None:
    @mcp.tool()
    async def sync_chat_cache(
        chat_ref: str,
        full: bool = False,
        use_takeout: bool = False,
    ) -> dict:
        """Sync one Telegram chat into the local SQLite cache."""
        canonical_chat_ref = await _canonical_chat_ref(chat_ref)
        connection = connect_cache()
        try:
            ensure_cache_schema(connection)
            if full:
                with connection:
                    clear_chat_cache(connection, canonical_chat_ref)

            state = get_chat_sync_state(connection, canonical_chat_ref)
            cursor = 0 if full or state is None else state["max_cached_id"]
            fetched_count = 0
            batch_count = 0

            while True:
                batch = await fetch_bulk_history_payload(
                    chat_ref=canonical_chat_ref,
                    since_message_id=cursor,
                    max_messages=50_000,
                    takeout=use_takeout,
                )
                batch_count += 1
                messages = batch["messages"]
                if messages:
                    with connection:
                        upsert_cached_messages(connection, messages)
                        update_chat_sync_state(connection, canonical_chat_ref, batch["to_id"])
                    fetched_count += len(messages)
                    cursor = batch["to_id"]

                if not batch["truncated"] or batch["count"] == 0:
                    break
                if batch["next_since_message_id"] is None:
                    break
                cursor = batch["next_since_message_id"]

            state = get_chat_sync_state(connection, canonical_chat_ref)
            cached_count = connection.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE chat_ref = ?",
                (canonical_chat_ref,),
            ).fetchone()["count"]
            return {
                "chat_ref": canonical_chat_ref,
                "full": full,
                "used_takeout": use_takeout,
                "fetched_count": fetched_count,
                "cached_count": cached_count,
                "batch_count": batch_count,
                "max_cached_id": state["max_cached_id"] if state else 0,
            }
        finally:
            connection.close()

    @mcp.tool()
    async def search_cache(
        chat_ref: str | None = None,
        query: str | None = None,
        from_user: str | None = None,
        min_date: str | None = None,
        max_date: str | None = None,
        limit: int = 100,
        auto_sync_seconds: int = 0,
    ) -> dict:
        """Search cached Telegram messages with optional FTS5 matching."""
        resolved_chat_ref = await _canonical_chat_ref(chat_ref) if chat_ref else None
        resolved_sender_ref = await _sender_ref(from_user)
        if resolved_chat_ref and auto_sync_seconds > 0:
            needs_sync = False
            sync_connection = connect_cache()
            try:
                ensure_cache_schema(sync_connection)
                state = get_chat_sync_state(sync_connection, resolved_chat_ref)
                now = int(datetime.now(tz=UTC).timestamp())
                needs_sync = state is None or now - state["last_synced_at"] >= auto_sync_seconds
            finally:
                sync_connection.close()
            if needs_sync:
                await sync_chat_cache(chat_ref=resolved_chat_ref)

        connection = connect_cache()
        try:
            ensure_cache_schema(connection)
            messages = search_cached_messages(
                connection,
                chat_ref=resolved_chat_ref,
                query=query,
                sender_ref=resolved_sender_ref,
                min_date=min_date,
                max_date=max_date,
                limit=limit,
            )
            return {
                "chat_ref": resolved_chat_ref,
                "query": query,
                "sender_ref": resolved_sender_ref,
                "count": len(messages),
                "messages": messages,
            }
        finally:
            connection.close()

    @mcp.tool()
    async def aggregate_cache(
        chat_ref: str,
        min_date: str | None = None,
        max_date: str | None = None,
        group_by: str = "day",
    ) -> dict:
        """Aggregate cached Telegram messages by day, week, or sender."""
        canonical_chat_ref = await _canonical_chat_ref(chat_ref)
        connection = connect_cache()
        try:
            ensure_cache_schema(connection)
            buckets = aggregate_cached_messages(
                connection,
                chat_ref=canonical_chat_ref,
                min_date=min_date,
                max_date=max_date,
                group_by=group_by,
            )
            return {
                "chat_ref": canonical_chat_ref,
                "group_by": group_by,
                "count": len(buckets),
                "buckets": buckets,
            }
        finally:
            connection.close()

    @mcp.tool()
    async def cache_status() -> dict:
        """Show cache path, db size, and sync status for cached chats."""
        connection = connect_cache()
        try:
            ensure_cache_schema(connection)
            return build_cache_status(connection)
        finally:
            connection.close()

    @mcp.tool()
    async def summarize_chat_history(
        chat_ref: str,
        min_date: str | None = None,
        max_date: str | None = None,
        chunk_size: int = 500,
        chunk_index: int = 0,
    ) -> dict:
        """Return one chunk of cached Telegram history for map-reduce summarization."""
        if chunk_size <= 0:
            raise ValueError("chunk_size must be > 0")
        if chunk_index < 0:
            raise ValueError("chunk_index must be >= 0")

        canonical_chat_ref = await _canonical_chat_ref(chat_ref)
        connection = connect_cache()
        try:
            ensure_cache_schema(connection)
            state = get_chat_sync_state(connection, canonical_chat_ref)
            if state is None:
                raise RuntimeError(
                    f"Chat {canonical_chat_ref} is not cached yet. Run sync_chat_cache first."
                )

            messages = load_cached_messages(
                connection,
                chat_ref=canonical_chat_ref,
                min_date=min_date,
                max_date=max_date,
            )
            if not messages:
                return {
                    "chat_ref": canonical_chat_ref,
                    "message_count": 0,
                    "chunk_size": chunk_size,
                    "chunk_index": chunk_index,
                    "chunk_count": 0,
                    "next_chunk_index": None,
                    "messages": [],
                }

            chunk_count = math.ceil(len(messages) / chunk_size)
            if chunk_index >= chunk_count:
                raise ValueError(
                    f"chunk_index {chunk_index} is out of range for {chunk_count} chunks."
                )

            start = chunk_index * chunk_size
            chunk = messages[start : start + chunk_size]
            return {
                "chat_ref": canonical_chat_ref,
                "message_count": len(messages),
                "chunk_size": chunk_size,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "next_chunk_index": chunk_index + 1 if chunk_index + 1 < chunk_count else None,
                "from_id": chunk[0]["id"],
                "to_id": chunk[-1]["id"],
                "messages": chunk,
            }
        finally:
            connection.close()
