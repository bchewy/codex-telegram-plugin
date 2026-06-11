from __future__ import annotations

from datetime import UTC, datetime
import math

from ..cache import (
    aggregate_cached_messages,
    cache_status as build_cache_status,
    clear_chat_cache,
    connect_cache,
    count_cached_messages,
    ensure_cache_schema,
    get_chat_sync_state,
    load_cached_message_chunk,
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
        max_messages_per_batch: int = 5_000,
        max_batches: int | None = None,
    ) -> dict:
        """Sync one Telegram chat into the local SQLite cache."""
        if max_messages_per_batch <= 0:
            raise ValueError("max_messages_per_batch must be > 0")
        if max_batches is not None and max_batches <= 0:
            raise ValueError("max_batches must be > 0")
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
            stopped_due_to_batch_limit = False
            older_history_uncached = False
            oldest_fetched_id: int | None = None

            while True:
                batch = await fetch_bulk_history_payload(
                    chat_ref=canonical_chat_ref,
                    since_message_id=cursor,
                    max_messages=max_messages_per_batch,
                    takeout=use_takeout,
                    tool_name="sync_chat_cache",
                )
                batch_count += 1
                messages = batch["messages"]
                if messages:
                    with connection:
                        upsert_cached_messages(connection, messages)
                        update_chat_sync_state(connection, canonical_chat_ref, batch["to_id"])
                    fetched_count += len(messages)
                    cursor = batch["to_id"]

                # Bootstrap path leaves older history unfetched when it hits
                # max_messages — propagate that signal so callers don't
                # mistake a bootstrap-capped sync for a complete one. Forward-
                # walk batches never set this flag.
                if batch.get("older_history_uncached"):
                    older_history_uncached = True
                if batch.get("oldest_fetched_id") is not None:
                    if oldest_fetched_id is None or batch["oldest_fetched_id"] < oldest_fetched_id:
                        oldest_fetched_id = batch["oldest_fetched_id"]

                if max_batches is not None and batch_count >= max_batches and batch["truncated"]:
                    stopped_due_to_batch_limit = True
                    break
                if not batch["truncated"] or batch["count"] == 0:
                    break
                if batch["next_since_message_id"] is None:
                    break
                cursor = batch["next_since_message_id"]

            state = get_chat_sync_state(connection, canonical_chat_ref)
            if state is None:
                # Empty chats yield no messages, but the sync still happened.
                # Record it so auto-sync staleness checks and summarize_chat_history
                # treat the chat as synced instead of retrying forever.
                with connection:
                    update_chat_sync_state(connection, canonical_chat_ref, 0)
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
                "max_messages_per_batch": max_messages_per_batch,
                "max_batches": max_batches,
                "truncated": stopped_due_to_batch_limit,
                "max_cached_id": state["max_cached_id"] if state else 0,
                # True if the bootstrap branch hit its message cap and there
                # are likely older messages in the chat that were not fetched.
                # Callers that need exhaustive history must NOT treat the
                # cache as complete when this is True.
                "older_history_uncached": older_history_uncached,
                "oldest_fetched_id": oldest_fetched_id,
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
        offset: int = 0,
        auto_sync_seconds: int = 0,
        compact: bool = False,
        text_limit: int = 240,
    ) -> dict:
        """Search cached Telegram messages with optional FTS5 matching."""
        if limit <= 0:
            raise ValueError("limit must be > 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        resolved_chat_ref = await _canonical_chat_ref(chat_ref) if chat_ref else None
        resolved_sender_ref = await _sender_ref(from_user)
        auto_synced = False
        auto_sync_truncated = False
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
                # Bound the inline sync to one batch so a stale chat freshens
                # quickly without an unbounded backfill blocking the search.
                sync_result = await sync_chat_cache(
                    chat_ref=resolved_chat_ref,
                    max_batches=1,
                )
                auto_synced = True
                auto_sync_truncated = bool(sync_result.get("truncated"))

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
                limit=limit + 1,
                offset=offset,
                compact=compact,
                text_limit=text_limit,
            )
            has_more = len(messages) > limit
            page = messages[:limit]
            return {
                "chat_ref": resolved_chat_ref,
                "query": query,
                "sender_ref": resolved_sender_ref,
                "count": len(page),
                "limit": limit,
                "offset": offset,
                "next_offset": offset + limit if has_more else None,
                "has_more": has_more,
                "compact": compact,
                "auto_synced": auto_synced,
                "auto_sync_truncated": auto_sync_truncated,
                "messages": page,
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

            message_count = count_cached_messages(
                connection,
                chat_ref=canonical_chat_ref,
                min_date=min_date,
                max_date=max_date,
            )
            if not message_count:
                return {
                    "chat_ref": canonical_chat_ref,
                    "message_count": 0,
                    "chunk_size": chunk_size,
                    "chunk_index": chunk_index,
                    "chunk_count": 0,
                    "next_chunk_index": None,
                    "messages": [],
                }

            chunk_count = math.ceil(message_count / chunk_size)
            if chunk_index >= chunk_count:
                raise ValueError(
                    f"chunk_index {chunk_index} is out of range for {chunk_count} chunks."
                )

            start = chunk_index * chunk_size
            chunk = load_cached_message_chunk(
                connection,
                chat_ref=canonical_chat_ref,
                min_date=min_date,
                max_date=max_date,
                limit=chunk_size,
                offset=start,
            )
            return {
                "chat_ref": canonical_chat_ref,
                "message_count": message_count,
                "chunk_size": chunk_size,
                "chunk_index": chunk_index,
                "chunk_count": chunk_count,
                "next_chunk_index": chunk_index + 1 if chunk_index + 1 < chunk_count else None,
                "from_id": chunk[0]["id"] if chunk else None,
                "to_id": chunk[-1]["id"] if chunk else None,
                "messages": chunk,
            }
        finally:
            connection.close()
