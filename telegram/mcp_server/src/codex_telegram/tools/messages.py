from __future__ import annotations

import asyncio
from datetime import timedelta
from itertools import islice

from telethon import errors, functions, types, utils as tg_utils

from ..client import (
    TelegramFloodWaitError,
    get_client,
    get_history_client,
    invalidate_dialog_cache,
    list_all_dialogs,
    with_flood_wait,
)
from ..helpers import (
    coerce_message_ids,
    dialog_to_dict,
    iter_message_dicts,
    message_to_dict,
    parse_datetime,
    peer_ref,
    resolve_entity,
    resolve_entity_fuzzy,
    resolve_input_peer,
    to_iso,
)
from ..safety import require_destructive

_ONE_MICROSECOND = timedelta(microseconds=1)
GET_UNREAD_CONCURRENCY = 4


def _within_range(message, min_date, max_date) -> bool:
    if min_date and message.date < min_date:
        return False
    if max_date and message.date > max_date:
        return False
    return True


def _validate_date_window(min_date, max_date) -> None:
    if min_date and max_date and min_date > max_date:
        raise ValueError("min_date must be <= max_date")


async def _load_dialog(client, entity):
    dialogs = await list_all_dialogs(client)
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


async def _search_messages_window(
    client,
    entity,
    *,
    query: str,
    limit: int,
    min_date: str | None = None,
    max_date: str | None = None,
    from_user=None,
    scan_limit: int = 1_000,
    offset_id: int = 0,
) -> dict:
    if not query or not query.strip():
        raise ValueError("query must not be blank")
    if offset_id < 0:
        raise ValueError("offset_id must be >= 0")
    if limit <= 0:
        return {
            "messages": [],
            "scanned_count": 0,
            "has_more": False,
            "scan_limit_reached": False,
            "next_offset": None,
        }
    if scan_limit <= 0:
        raise ValueError("scan_limit must be > 0")

    lower = parse_datetime(min_date)
    upper = parse_datetime(max_date)
    _validate_date_window(lower, upper)

    offset_date = upper + _ONE_MICROSECOND if upper else None
    collected = []
    scanned_count = 0
    stopped_at_lower_bound = False
    target_count = limit + 1
    last_scanned_date = None
    last_scanned_id: int | None = None

    async for message in client.iter_messages(
        entity,
        search=query,
        from_user=from_user,
        offset_date=offset_date,
        offset_id=offset_id,
        limit=scan_limit,
    ):
        scanned_count += 1
        last_scanned_date = message.date
        last_scanned_id = message.id
        if lower and message.date < lower:
            stopped_at_lower_bound = True
            break
        if not _within_range(message, lower, upper):
            continue
        collected.append(message)
        if len(collected) >= target_count:
            break

    has_more = len(collected) > limit
    scan_limit_reached = scanned_count >= scan_limit and not stopped_at_lower_bound and not has_more

    next_offset: dict | None = None
    if has_more:
        boundary = collected[limit]
        # Telethon's offset_id is exclusive (returns messages with id < offset_id).
        # We want the boundary message itself on the next page, so add 1.
        next_offset = {"date": to_iso(boundary.date), "id": boundary.id + 1}
    elif scan_limit_reached and last_scanned_id is not None:
        # The last scanned message was either returned in this page or skipped
        # by the date filter; either way we don't want to revisit it. Telethon
        # filters strictly with offset_id, so passing it back skips that id.
        next_offset = {
            "date": to_iso(last_scanned_date) if last_scanned_date else None,
            "id": last_scanned_id,
        }

    return {
        "messages": collected[:limit],
        "scanned_count": scanned_count,
        "has_more": has_more,
        "scan_limit_reached": scan_limit_reached,
        "next_offset": next_offset,
    }


def _message_offset_peer_ref(message) -> str | None:
    for peer in (getattr(message, "input_chat", None), getattr(message, "peer_id", None)):
        if peer is None:
            continue
        try:
            return peer_ref(peer)
        except TypeError:
            continue
    return None


def _global_search_offset_rate(response, message) -> int:
    next_rate = getattr(response, "next_rate", None)
    if next_rate is not None:
        return next_rate

    message_date = getattr(message, "date", None)
    if message_date is None:
        return 0
    return int(message_date.timestamp())


async def _search_global_messages_window(
    client,
    *,
    query: str,
    limit: int,
    min_date: str | None = None,
    max_date: str | None = None,
    scan_limit: int = 1_000,
    offset_id: int = 0,
    offset_peer: str | None = None,
    offset_rate: int = 0,
) -> dict:
    if not query or not query.strip():
        raise ValueError("query must not be blank")
    if offset_id < 0:
        raise ValueError("offset_id must be >= 0")
    if offset_rate < 0:
        raise ValueError("offset_rate must be >= 0")
    if limit <= 0:
        return {
            "messages": [],
            "scanned_count": 0,
            "has_more": False,
            "scan_limit_reached": False,
            "next_offset": None,
        }
    if scan_limit <= 0:
        raise ValueError("scan_limit must be > 0")

    lower = parse_datetime(min_date)
    upper = parse_datetime(max_date)
    _validate_date_window(lower, upper)

    current_offset_peer = (
        await resolve_input_peer(client, offset_peer)
        if offset_peer
        else types.InputPeerEmpty()
    )
    current_offset_id = offset_id
    current_offset_rate = offset_rate
    request_max_date = upper + _ONE_MICROSECOND if upper else None

    collected = []
    scanned_count = 0
    stopped_at_lower_bound = False
    target_count = limit + 1
    last_scanned_offset: dict | None = None
    last_returned_offset: dict | None = None
    next_offset: dict | None = None

    while scanned_count < scan_limit and len(collected) < target_count:
        response = await client(
            functions.messages.SearchGlobalRequest(
                q=query,
                filter=types.InputMessagesFilterEmpty(),
                min_date=lower,
                max_date=request_max_date,
                offset_rate=current_offset_rate,
                offset_peer=current_offset_peer,
                offset_id=current_offset_id,
                limit=1,
            )
        )
        raw_messages = getattr(response, "messages", [])
        if not raw_messages:
            break

        entities = {
            tg_utils.get_peer_id(entity): entity
            for entity in [*getattr(response, "users", []), *getattr(response, "chats", [])]
        }
        advanced = False
        for message in raw_messages:
            if isinstance(message, types.MessageEmpty):
                continue
            if hasattr(message, "_finish_init"):
                message._finish_init(client, entities, None)

            scanned_count += 1
            advanced = True
            current_offset_id = message.id
            current_offset_peer = getattr(message, "input_chat", None) or types.InputPeerEmpty()
            current_offset_rate = _global_search_offset_rate(response, message)
            last_scanned_offset = {
                "date": to_iso(message.date),
                "id": message.id,
                "offset_peer": _message_offset_peer_ref(message),
                "offset_rate": current_offset_rate,
            }

            if lower and message.date < lower:
                stopped_at_lower_bound = True
                break
            if not _within_range(message, lower, upper):
                continue
            collected.append(message)
            if len(collected) <= limit:
                last_returned_offset = last_scanned_offset
            if len(collected) >= target_count:
                break

        if stopped_at_lower_bound or len(collected) >= target_count:
            break
        if not advanced:
            break

    has_more = len(collected) > limit and not stopped_at_lower_bound
    scan_limit_reached = scanned_count >= scan_limit and not stopped_at_lower_bound and not has_more
    if has_more:
        next_offset = last_returned_offset
    elif scan_limit_reached:
        next_offset = last_scanned_offset

    return {
        "messages": collected[:limit],
        "scanned_count": scanned_count,
        "has_more": has_more,
        "scan_limit_reached": scan_limit_reached,
        "next_offset": next_offset,
    }


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
                    raise TelegramFloodWaitError(
                        seconds=exc.seconds,
                        tool_name="bulk_fetch_history",
                        attempts=attempts,
                    ) from exc
                await asyncio.sleep(exc.seconds)


async def _fetch_bulk_history_bootstrap(
    history_client,
    entity,
    *,
    chat_ref_value: str,
    until_message_id: int | None,
    max_messages: int,
    include_empty: bool,
    takeout: bool,
) -> dict:
    """Fetch the newest `max_messages` messages via Telethon offset pagination.

    Used when there's no resume cursor (`since_message_id == 0`). ID-range
    forward-walking from id=1 is catastrophic for chats whose lowest used
    message id sits hundreds of thousands deep (Saved Messages can easily
    start at 100k+), so the bootstrap walks newest-first instead.

    Returns the same envelope shape as the forward-walk path. `truncated`
    and `next_since_message_id` always describe the forward direction
    (there's nothing newer to fetch after the bootstrap), so both are
    set to False/None. A separate field `older_history_uncached` signals
    when the bootstrap hit `max_messages` and there may be older messages
    that were intentionally not fetched — callers should not assume the
    cache is exhaustive when this is True. `oldest_fetched_id` is exposed
    so a future backfill path can resume below the bootstrap's coverage.
    """
    payloads: list[dict] = []
    deleted_count = 0
    raw_count = 0
    raw_lowest_fetched_id: int | None = None
    raw_highest_fetched_id: int | None = None

    iter_kwargs: dict = {"limit": max_messages}
    if until_message_id is not None:
        # `iter_messages.offset_id` is exclusive (returns id < offset_id).
        # Add 1 so `until_message_id` is inclusive.
        iter_kwargs["offset_id"] = until_message_id + 1

    async for message in history_client.iter_messages(entity, **iter_kwargs):
        raw_count += 1
        message_id = getattr(message, "id", None)
        if message_id is not None:
            raw_lowest_fetched_id = (
                message_id
                if raw_lowest_fetched_id is None
                else min(raw_lowest_fetched_id, message_id)
            )
            raw_highest_fetched_id = (
                message_id
                if raw_highest_fetched_id is None
                else max(raw_highest_fetched_id, message_id)
            )
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

    payloads.sort(key=lambda item: item["id"] or 0)
    payloads = payloads[:max_messages]

    # Count RAW items yielded by iter_messages — not filtered payloads. If
    # the iterator hit max_messages worth of items there's likely more older
    # history. Filtering deleted/empty messages doesn't change whether the
    # underlying chat had more to read.
    older_history_uncached = raw_count >= max_messages

    return {
        "chat_ref": chat_ref_value,
        "count": len(payloads),
        "deleted_count": deleted_count,
        "from_id": payloads[0]["id"] if payloads else raw_lowest_fetched_id,
        "to_id": payloads[-1]["id"] if payloads else raw_highest_fetched_id,
        "messages": payloads,
        "truncated": False,
        "next_since_message_id": None,
        "used_takeout": takeout,
        "older_history_uncached": older_history_uncached,
        "oldest_fetched_id": payloads[0]["id"] if payloads else raw_lowest_fetched_id,
    }


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
        # Bootstrap path: first sync (or `full=True` clear-then-sync) has no
        # resume cursor. Walking ID-range forward from id=1 stalls badly on
        # chats whose lowest message id is well above 1, so use Telethon's
        # newest-first offset pagination instead.
        if since_message_id == 0:
            return await _fetch_bulk_history_bootstrap(
                history_client,
                entity,
                chat_ref_value=chat_ref_value,
                until_message_id=until_message_id,
                max_messages=max_messages,
                include_empty=include_empty,
                takeout=takeout,
            )

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
                "older_history_uncached": False,
                "oldest_fetched_id": None,
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
                "older_history_uncached": False,
                "oldest_fetched_id": None,
            }

        semaphore = asyncio.Semaphore(concurrency)
        payloads: list[dict] = []
        deleted_count = 0
        raw_lowest_fetched_id: int | None = None
        raw_highest_fetched_id: int | None = None
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
                    message_id = getattr(message, "id", None)
                    if message_id is not None:
                        raw_lowest_fetched_id = (
                            message_id
                            if raw_lowest_fetched_id is None
                            else min(raw_lowest_fetched_id, message_id)
                        )
                        raw_highest_fetched_id = (
                            message_id
                            if raw_highest_fetched_id is None
                            else max(raw_highest_fetched_id, message_id)
                        )
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
        next_since_message_id = (
            payloads[-1]["id"]
            if not scan_complete and payloads
            else raw_highest_fetched_id if not scan_complete else None
        )

        return {
            "chat_ref": chat_ref_value,
            "count": len(payloads),
            "deleted_count": deleted_count,
            "from_id": payloads[0]["id"] if payloads else raw_lowest_fetched_id,
            "to_id": payloads[-1]["id"] if payloads else raw_highest_fetched_id,
            "messages": payloads,
            "truncated": not scan_complete,
            "next_since_message_id": next_since_message_id,
            "used_takeout": takeout,
            # Forward-walk resumes from `since_message_id`, so this path
            # never leaves older history behind by design.
            "older_history_uncached": False,
            "oldest_fetched_id": payloads[0]["id"] if payloads else raw_lowest_fetched_id,
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
        _validate_date_window(lower, upper)
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

        return {
            "chat_ref": peer_ref(entity),
            "count": len(filtered[:limit]),
            "messages": iter_message_dicts(filtered[:limit]),
        }

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

        dialogs = await list_all_dialogs(client)
        unread_dialogs = [dialog for dialog in dialogs if dialog.unread_count > 0]

        semaphore = asyncio.Semaphore(GET_UNREAD_CONCURRENCY)

        async def _fetch_unread(dialog, remaining_limit):
            async with semaphore:
                read_max = getattr(getattr(dialog, "dialog", None), "read_inbox_max_id", 0)
                per_call_limit = min(remaining_limit, dialog.unread_count + 10)
                fetched = await client.get_messages(
                    dialog.entity,
                    limit=per_call_limit,
                    min_id=read_max,
                )
                return [message_to_dict(message) for message in fetched if not message.out]

        results = []
        flat_messages = []
        dialog_errors: list[dict] = []
        remaining = limit
        cursor = 0
        # Telegram's `unread_count` is an estimate and routinely underreports
        # (chats where the local copy is ahead of the server). One round of
        # fan-out can under-fetch; loop until we hit `limit` or exhaust
        # candidates so the caller never silently gets fewer messages than
        # requested.
        while remaining > 0 and cursor < len(unread_dialogs):
            batch: list = []
            running_unread = 0
            while cursor < len(unread_dialogs):
                dialog = unread_dialogs[cursor]
                batch.append(dialog)
                running_unread += dialog.unread_count
                cursor += 1
                if running_unread >= remaining:
                    break

            # return_exceptions=True so one dialog's failure (e.g. kicked
            # channel raising ChannelPrivateError) doesn't cancel siblings
            # and lose otherwise-valid unread messages from healthy dialogs.
            # Special-cased below: FloodWaitError re-raises (outer
            # `with_flood_wait` handles backoff) and any non-`Exception`
            # BaseException (CancelledError, KeyboardInterrupt, SystemExit)
            # must also propagate rather than be silently logged.
            fetched = await asyncio.gather(
                *(_fetch_unread(dialog, remaining) for dialog in batch),
                return_exceptions=True,
            )

            # Re-raise FloodWaitError using the largest `seconds` so the
            # caller's backoff respects the worst-case wait rather than
            # whichever dialog happened to be first in the batch.
            flood_items = [
                item for item in fetched
                if isinstance(item, errors.FloodWaitError)
            ]
            if flood_items:
                raise max(flood_items, key=lambda exc: getattr(exc, "seconds", 0))
            for item in fetched:
                if isinstance(item, BaseException) and not isinstance(item, Exception):
                    # CancelledError, KeyboardInterrupt, SystemExit — these
                    # must propagate; turning them into a structured dialog
                    # error would swallow task cancellation and shutdown.
                    raise item

            for dialog, item in zip(batch, fetched, strict=True):
                if remaining <= 0:
                    break
                if isinstance(item, Exception):
                    dialog_errors.append(
                        {
                            "chat_ref": peer_ref(dialog.entity) if dialog.entity else None,
                            "error": str(item),
                            "error_type": type(item).__name__,
                        }
                    )
                    continue
                take = item[:remaining]
                flat_messages.extend(take)
                results.append(
                    {
                        "dialog": dialog_to_dict(dialog),
                        "messages": take,
                    }
                )
                remaining -= len(take)

        return {
            "dialog_count": len(results),
            "messages": flat_messages,
            "results": results,
            "errors": dialog_errors,
        }

    @mcp.tool()
    @with_flood_wait
    async def search_messages_global(
        query: str,
        limit: int = 50,
        min_date: str | None = None,
        max_date: str | None = None,
        scan_limit: int = 1_000,
        offset_id: int = 0,
        offset_peer: str | None = None,
        offset_rate: int = 0,
    ) -> dict:
        """Search across all dialogs with bounded global-search pagination.

        To resume from a previous call, pass `offset_id`, `offset_peer`, and
        `offset_rate` from `next_offset`. Telegram global search uses all three
        cursor fields because message ids are scoped per dialog.
        """
        client = await get_client()
        result = await _search_global_messages_window(
            client,
            query=query,
            limit=limit,
            min_date=min_date,
            max_date=max_date,
            scan_limit=scan_limit,
            offset_id=offset_id,
            offset_peer=offset_peer,
            offset_rate=offset_rate,
        )
        found = result["messages"]
        return {
            "query": query,
            "count": len(found),
            "scanned_count": result["scanned_count"],
            "has_more": result["has_more"],
            "scan_limit_reached": result["scan_limit_reached"],
            "next_offset": result["next_offset"],
            "messages": iter_message_dicts(found),
        }

    @mcp.tool()
    @with_flood_wait
    async def search_messages_in_chat(
        chat_ref: str,
        query: str,
        limit: int = 50,
        from_user: str | None = None,
        min_date: str | None = None,
        max_date: str | None = None,
        scan_limit: int = 1_000,
        offset_id: int = 0,
    ) -> dict:
        """Search messages within one dialog with bounded pagination through the date window.

        To resume from a previous call, pass `offset_id` from the previous
        response's `next_offset.id`. The cursor uses Telegram's exclusive
        message-id ordering so messages are never returned twice.
        """
        client = await get_client()
        entity = await resolve_entity_fuzzy(client, chat_ref)
        sender = await resolve_entity_fuzzy(client, from_user) if from_user else None
        result = await _search_messages_window(
            client,
            entity,
            query=query,
            limit=limit,
            min_date=min_date,
            max_date=max_date,
            from_user=sender,
            scan_limit=scan_limit,
            offset_id=offset_id,
        )
        found = result["messages"]
        return {
            "chat_ref": peer_ref(entity),
            "query": query,
            "count": len(found),
            "scanned_count": result["scanned_count"],
            "has_more": result["has_more"],
            "scan_limit_reached": result["scan_limit_reached"],
            "next_offset": result["next_offset"],
            "messages": iter_message_dicts(found),
        }

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
        invalidate_dialog_cache(client)
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
