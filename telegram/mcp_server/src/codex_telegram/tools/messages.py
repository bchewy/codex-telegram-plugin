from __future__ import annotations

import asyncio
from datetime import timedelta
from itertools import islice

from telethon import errors, types

from ..client import get_client, get_history_client, with_flood_wait
from ..helpers import (
    coerce_message_ids,
    dialog_to_dict,
    iter_message_dicts,
    message_to_dict,
    parse_datetime,
    peer_ref,
    resolve_entity,
    resolve_entity_fuzzy,
)
from ..safety import require_destructive

_ONE_MICROSECOND = timedelta(microseconds=1)


def _within_range(message, min_date, max_date) -> bool:
    if min_date and message.date < min_date:
        return False
    if max_date and message.date > max_date:
        return False
    return True


async def _load_dialog(client, entity):
    dialogs = await client.get_dialogs(limit=200)
    return next((item for item in dialogs if peer_ref(item.entity) == peer_ref(entity)), None)


def _as_message_list(value):
    if value is None:
        return []
    if isinstance(value, types.MessageEmpty):
        return [value]
    if hasattr(value, "id"):
        return [value]
    return list(value)


def _is_empty_message(message) -> bool:
    return message is None or isinstance(message, types.MessageEmpty)


def _message_payload(message, *, chat_ref_value: str, include_empty: bool) -> dict | None:
    if _is_empty_message(message):
        if not include_empty:
            return None
        return {
            "id": getattr(message, "id", None),
            "chat_ref": chat_ref_value,
            "deleted": True,
        }
    return message_to_dict(message)


def _iter_message_id_chunks(start_id: int, end_id: int, *, chunk_size: int = 100):
    current = start_id
    while current <= end_id:
        stop = min(current + chunk_size - 1, end_id)
        yield list(range(current, stop + 1))
        current = stop + 1


async def _fetch_message_chunk(client, entity, ids: list[int], semaphore: asyncio.Semaphore):
    async with semaphore:
        attempts = 0
        while True:
            try:
                return _as_message_list(await client.get_messages(entity, ids=ids))
            except errors.FloodWaitError as exc:
                attempts += 1
                if attempts > 1:
                    raise RuntimeError(
                        f"Telegram rate limited this request for {exc.seconds} seconds. "
                        "Wait for the flood window to expire and retry."
                    ) from exc
                await asyncio.sleep(exc.seconds)


async def fetch_bulk_history_payload(
    *,
    chat_ref: str,
    since_message_id: int = 0,
    until_message_id: int | None = None,
    max_messages: int = 50_000,
    concurrency: int = 8,
    include_empty: bool = False,
    takeout: bool = False,
    takeout_kwargs: dict | None = None,
) -> dict:
    if since_message_id < 0:
        raise ValueError("since_message_id must be >= 0")
    if until_message_id is not None and until_message_id < 0:
        raise ValueError("until_message_id must be >= 0")
    if max_messages <= 0:
        raise ValueError("max_messages must be > 0")
    if concurrency <= 0:
        raise ValueError("concurrency must be > 0")

    client = await get_client()
    entity = await resolve_entity_fuzzy(client, chat_ref)
    chat_ref_value = peer_ref(entity)

    async with get_history_client(use_takeout=takeout, takeout_kwargs=takeout_kwargs) as history_client:
        latest_messages = _as_message_list(await history_client.get_messages(entity, limit=1))
        if not latest_messages:
            return {
                "chat_ref": chat_ref_value,
                "count": 0,
                "deleted_count": 0,
                "from_id": None,
                "to_id": None,
                "messages": [],
                "truncated": False,
                "next_since_message_id": None,
                "used_takeout": takeout,
            }

        highest_id = latest_messages[0].id
        if until_message_id is not None:
            highest_id = min(highest_id, until_message_id)

        start_id = since_message_id + 1
        if highest_id < start_id:
            return {
                "chat_ref": chat_ref_value,
                "count": 0,
                "deleted_count": 0,
                "from_id": None,
                "to_id": None,
                "messages": [],
                "truncated": False,
                "next_since_message_id": None,
                "used_takeout": takeout,
            }

        semaphore = asyncio.Semaphore(concurrency)
        payloads: list[dict] = []
        deleted_count = 0
        chunk_iter = _iter_message_id_chunks(start_id, highest_id)
        scan_complete = True

        while True:
            batch_chunks = list(islice(chunk_iter, concurrency))
            if not batch_chunks:
                break

            batch_results = await asyncio.gather(
                *[
                    _fetch_message_chunk(history_client, entity, ids, semaphore)
                    for ids in batch_chunks
                ]
            )

            for chunk_messages in batch_results:
                for message in chunk_messages:
                    if _is_empty_message(message):
                        deleted_count += 1
                    payload = _message_payload(
                        message,
                        chat_ref_value=chat_ref_value,
                        include_empty=include_empty,
                    )
                    if payload is None:
                        continue
                    payloads.append(payload)
                    if len(payloads) >= max_messages:
                        scan_complete = False
                        break
                if not scan_complete:
                    break

            if not scan_complete:
                break

        payloads.sort(key=lambda item: item["id"] or 0)
        payloads = payloads[:max_messages]
        next_since_message_id = payloads[-1]["id"] if not scan_complete and payloads else None

        return {
            "chat_ref": chat_ref_value,
            "count": len(payloads),
            "deleted_count": deleted_count,
            "from_id": payloads[0]["id"] if payloads else None,
            "to_id": payloads[-1]["id"] if payloads else None,
            "messages": payloads,
            "truncated": not scan_complete,
            "next_since_message_id": next_since_message_id,
            "used_takeout": takeout,
        }


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def get_history(
        chat_ref: str,
        limit: int = 100,
        min_date: str | None = None,
        max_date: str | None = None,
        from_user: str | None = None,
    ) -> dict:
        """Fetch message history from one Telegram chat."""
        client = await get_client()
        entity = await resolve_entity_fuzzy(client, chat_ref)
        sender = await resolve_entity_fuzzy(client, from_user) if from_user else None
        lower = parse_datetime(min_date)
        upper = parse_datetime(max_date)
        filtered = []
        if lower:
            async for message in client.iter_messages(
                entity,
                offset_date=lower - _ONE_MICROSECOND,
                reverse=True,
                from_user=sender,
            ):
                if upper and message.date > upper:
                    break
                if not _within_range(message, lower, upper):
                    continue
                filtered.append(message)
                if len(filtered) >= limit:
                    break
        else:
            offset_id = 0
            offset_date = upper + _ONE_MICROSECOND if upper else None
            page_size = max(limit * 3, limit)
            for _ in range(10):
                batch = [
                    message
                    async for message in client.iter_messages(
                        entity,
                        limit=page_size,
                        offset_id=offset_id,
                        offset_date=offset_date,
                        from_user=sender,
                    )
                ]
                if not batch:
                    break

                for message in batch:
                    if _within_range(message, lower, upper):
                        filtered.append(message)
                        if len(filtered) >= limit:
                            break

                if len(filtered) >= limit:
                    break

                next_offset = batch[-1].id
                if next_offset == offset_id:
                    break
                offset_id = next_offset
                offset_date = None

        return {"chat_ref": peer_ref(entity), "count": len(filtered[:limit]), "messages": iter_message_dicts(filtered[:limit])}

    @mcp.tool()
    @with_flood_wait
    async def get_message_context(chat_ref: str, message_id: int, context_size: int = 3) -> dict:
        """Fetch messages around a specific Telegram message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        before, center, after = await asyncio.gather(
            client.get_messages(entity, limit=context_size, max_id=message_id),
            client.get_messages(entity, ids=message_id),
            client.get_messages(entity, limit=context_size, min_id=message_id, reverse=True),
        )
        center_messages = _as_message_list(center)
        if not center_messages:
            raise RuntimeError(f"Message {message_id} was not found in {chat_ref}.")

        combined = [
            *[message for message in _as_message_list(before) if not _is_empty_message(message)],
            *[message for message in center_messages if not _is_empty_message(message)],
            *[message for message in _as_message_list(after) if not _is_empty_message(message)],
        ]
        combined.sort(key=lambda message: message.id)
        return {
            "chat_ref": peer_ref(entity),
            "message_id": message_id,
            "count": len(combined),
            "messages": iter_message_dicts(combined),
        }

    @mcp.tool()
    @with_flood_wait
    async def get_unread(chat_ref: str | None = None, limit: int = 100) -> dict:
        """Fetch unread messages for one chat or across all dialogs with a flat aggregate list."""
        client = await get_client()

        if chat_ref:
            entity = await resolve_entity_fuzzy(client, chat_ref)
            dialog = await _load_dialog(client, entity)
            if dialog is None:
                raise RuntimeError(f"Could not find dialog metadata for {chat_ref}.")
            read_max = getattr(getattr(dialog, "dialog", None), "read_inbox_max_id", 0)
            messages = await client.get_messages(entity, limit=limit, min_id=read_max)
            unread = [message for message in messages if not message.out]
            return {
                "chat_ref": peer_ref(entity),
                "unread_count": dialog.unread_count,
                "messages": iter_message_dicts(unread[:limit]),
            }

        dialogs = await client.get_dialogs(limit=200)
        results = []
        flat_messages = []
        remaining = limit
        for dialog in dialogs:
            if dialog.unread_count <= 0 or remaining <= 0:
                continue
            read_max = getattr(getattr(dialog, "dialog", None), "read_inbox_max_id", 0)
            messages = await client.get_messages(dialog.entity, limit=min(remaining, dialog.unread_count + 10), min_id=read_max)
            unread = [message_to_dict(message) for message in messages if not message.out][:remaining]
            flat_messages.extend(unread)
            results.append(
                {
                    "dialog": dialog_to_dict(dialog),
                    "messages": unread,
                }
            )
            remaining -= len(unread)

        return {"dialog_count": len(results), "messages": flat_messages, "results": results}

    @mcp.tool()
    @with_flood_wait
    async def search_messages_global(
        query: str,
        limit: int = 50,
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> dict:
        """Search across all dialogs."""
        client = await get_client()
        lower = parse_datetime(min_date)
        upper = parse_datetime(max_date)
        messages = await client.get_messages(None, limit=max(limit * 3, limit), search=query)
        filtered = [message for message in messages if _within_range(message, lower, upper)]
        return {"query": query, "count": len(filtered[:limit]), "messages": iter_message_dicts(filtered[:limit])}

    @mcp.tool()
    @with_flood_wait
    async def search_messages_in_chat(
        chat_ref: str,
        query: str,
        limit: int = 50,
        from_user: str | None = None,
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> dict:
        """Search messages within one dialog."""
        client = await get_client()
        entity = await resolve_entity_fuzzy(client, chat_ref)
        sender = await resolve_entity_fuzzy(client, from_user) if from_user else None
        lower = parse_datetime(min_date)
        upper = parse_datetime(max_date)
        messages = await client.get_messages(
            entity,
            limit=max(limit * 3, limit),
            search=query,
            from_user=sender,
        )
        filtered = [message for message in messages if _within_range(message, lower, upper)]
        return {"chat_ref": peer_ref(entity), "query": query, "count": len(filtered[:limit]), "messages": iter_message_dicts(filtered[:limit])}

    @mcp.tool()
    @with_flood_wait
    async def init_takeout_session(
        contacts: bool = False,
        users: bool = True,
        chats: bool = True,
        megagroups: bool = True,
        channels: bool = True,
        files: bool = False,
    ) -> dict:
        """Start a Telegram takeout session for bulk export workflows."""
        takeout_kwargs = {
            "contacts": contacts,
            "users": users,
            "chats": chats,
            "megagroups": megagroups,
            "channels": channels,
            "files": files,
        }
        async with get_history_client(use_takeout=True, takeout_kwargs=takeout_kwargs) as takeout:
            await takeout.get_messages("me", limit=1)
        return {"ok": True, "takeout": takeout_kwargs}

    @mcp.tool()
    @with_flood_wait
    async def bulk_fetch_history(
        chat_ref: str,
        since_message_id: int = 0,
        until_message_id: int | None = None,
        max_messages: int = 50_000,
        concurrency: int = 8,
        include_empty: bool = False,
        takeout: bool = False,
    ) -> dict:
        """Bulk-fetch a Telegram chat by message-id range."""
        return await fetch_bulk_history_payload(
            chat_ref=chat_ref,
            since_message_id=since_message_id,
            until_message_id=until_message_id,
            max_messages=max_messages,
            concurrency=concurrency,
            include_empty=include_empty,
            takeout=takeout,
        )

    @mcp.tool()
    @with_flood_wait
    async def send_message(
        chat_ref: str,
        text: str,
        reply_to: int | None = None,
        parse_mode: str | None = "md",
        schedule_at: str | None = None,
        link_preview: bool = False,
        silent: bool = False,
    ) -> dict:
        """Send a text message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        message = await client.send_message(
            entity,
            text,
            reply_to=reply_to,
            parse_mode=parse_mode,
            link_preview=link_preview,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        return message_to_dict(message)

    @mcp.tool()
    @with_flood_wait
    async def reply_message(
        chat_ref: str,
        reply_to_message_id: int,
        text: str,
        parse_mode: str | None = "md",
        schedule_at: str | None = None,
        link_preview: bool = False,
    ) -> dict:
        """Reply to a specific Telegram message."""
        return await send_message(
            chat_ref=chat_ref,
            text=text,
            reply_to=reply_to_message_id,
            parse_mode=parse_mode,
            schedule_at=schedule_at,
            link_preview=link_preview,
        )

    @mcp.tool()
    @with_flood_wait
    async def edit_message(
        chat_ref: str,
        message_id: int,
        text: str,
        parse_mode: str | None = "md",
        link_preview: bool = False,
    ) -> dict:
        """Edit a previously sent Telegram message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        message = await client.edit_message(
            entity,
            message_id,
            text,
            parse_mode=parse_mode,
            link_preview=link_preview,
        )
        return message_to_dict(message)

    @mcp.tool()
    @with_flood_wait
    async def delete_messages(
        chat_ref: str,
        message_ids: int | list[int],
        revoke: bool = True,
        confirm: bool = False,
    ) -> dict:
        """Delete one or more messages."""
        require_destructive("delete_messages", confirm)
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        ids = coerce_message_ids(message_ids)
        result = await client.delete_messages(entity, ids, revoke=revoke)
        return {"chat_ref": peer_ref(entity), "message_ids": ids, "deleted_count": len(result)}

    @mcp.tool()
    @with_flood_wait
    async def forward_messages(
        from_chat_ref: str,
        to_chat_ref: str,
        message_ids: int | list[int],
        silent: bool = False,
        schedule_at: str | None = None,
    ) -> dict:
        """Forward messages from one chat to another."""
        client = await get_client()
        source = await resolve_entity(client, from_chat_ref)
        target = await resolve_entity(client, to_chat_ref)
        ids = coerce_message_ids(message_ids)
        forwarded = await client.forward_messages(
            target,
            ids,
            from_peer=source,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        return {
            "from_chat_ref": peer_ref(source),
            "to_chat_ref": peer_ref(target),
            "count": len(forwarded),
            "messages": iter_message_dicts(forwarded),
        }

    @mcp.tool()
    @with_flood_wait
    async def mark_as_read(chat_ref: str, message_id: int | None = None) -> dict:
        """Mark messages as read up to an optional message id."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.send_read_acknowledge(entity, max_id=message_id)
        return {"chat_ref": peer_ref(entity), "max_id": message_id, "marked_read": True}

    @mcp.tool()
    @with_flood_wait
    async def get_message_by_id(chat_ref: str, message_id: int) -> dict:
        """Fetch one message by id."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        message = await client.get_messages(entity, ids=message_id)
        if not message:
            raise RuntimeError(f"Message {message_id} was not found in {chat_ref}.")
        return message_to_dict(message)

    @mcp.tool()
    @with_flood_wait
    async def pin_message(chat_ref: str, message_id: int, notify: bool = False) -> dict:
        """Pin a message in a chat."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.pin_message(entity, message_id, notify=notify)
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "pinned": True}

    @mcp.tool()
    @with_flood_wait
    async def unpin_message(chat_ref: str, message_id: int | None = None, notify: bool = False) -> dict:
        """Unpin one message or all pinned messages."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.unpin_message(entity, message_id, notify=notify)
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "pinned": False}

    @mcp.tool()
    @with_flood_wait
    async def get_pinned_messages(chat_ref: str, limit: int = 20) -> dict:
        """Fetch pinned messages in a dialog."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        messages = await client.get_messages(
            entity,
            limit=limit,
            filter=types.InputMessagesFilterPinned(),
        )
        return {"chat_ref": peer_ref(entity), "count": len(messages), "messages": iter_message_dicts(messages)}
