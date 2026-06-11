from __future__ import annotations

from datetime import UTC, datetime

from telethon import functions, types

from ..client import get_client, invalidate_dialog_cache, list_all_dialogs, with_flood_wait
from ..helpers import (
    dialog_to_dict,
    iter_message_dicts,
    parse_datetime,
    peer_ref,
    resolve_entity,
    resolve_entity_fuzzy,
)


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def list_dialogs(
        limit: int = 100,
        archived: bool | None = None,
        query: str | None = None,
        ignore_pinned: bool = False,
    ) -> dict:
        """List Telegram dialogs ordered like the official client."""
        if limit <= 0:
            raise ValueError("limit must be > 0")
        client = await get_client()
        # A query must filter the full dialog list before the limit is
        # applied, or matches outside the first `limit` dialogs are missed.
        dialogs = await client.get_dialogs(
            limit=None if query else limit,
            archived=archived,
            ignore_pinned=ignore_pinned,
        )
        items = [dialog_to_dict(dialog) for dialog in dialogs]
        if query:
            lowered = query.casefold()
            items = [
                item
                for item in items
                if lowered in (item["title"] or "").casefold()
                or lowered in (item["display_name"] or "").casefold()
            ][:limit]
        return {"count": len(items), "dialogs": items}

    @mcp.tool()
    @with_flood_wait
    async def get_dialog(chat_ref: str, history_limit: int = 20) -> dict:
        """Return one dialog plus recent history."""
        client = await get_client()
        entity = await resolve_entity_fuzzy(client, chat_ref)
        dialogs = await list_all_dialogs(client)
        dialog = next((item for item in dialogs if peer_ref(item.entity) == peer_ref(entity)), None)

        history = await client.get_messages(entity, limit=history_limit)
        response = dialog_to_dict(dialog) if dialog else {
            "chat_ref": peer_ref(entity),
            "id": getattr(entity, "id", None),
            "kind": type(entity).__name__,
            "title": getattr(entity, "title", None),
            "display_name": getattr(entity, "first_name", None) or getattr(entity, "title", None),
        }
        response["recent_messages"] = iter_message_dicts(history)
        return response

    @mcp.tool()
    @with_flood_wait
    async def archive_dialog(chat_ref: str) -> dict:
        """Move a dialog into the archived folder."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.edit_folder(entity, 1)
        invalidate_dialog_cache(client)
        return {"chat_ref": peer_ref(entity), "archived": True}

    @mcp.tool()
    @with_flood_wait
    async def unarchive_dialog(chat_ref: str) -> dict:
        """Move a dialog out of the archived folder."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.edit_folder(entity, 0)
        invalidate_dialog_cache(client)
        return {"chat_ref": peer_ref(entity), "archived": False}

    @mcp.tool()
    @with_flood_wait
    async def mute_dialog(
        chat_ref: str,
        mute_until: str | None = None,
        show_previews: bool = False,
        silent: bool = True,
    ) -> dict:
        """Mute notifications for a dialog."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await client.get_input_entity(entity)
        until = parse_datetime(mute_until) or datetime(2100, 1, 1, tzinfo=UTC)
        await client(
            functions.account.UpdateNotifySettingsRequest(
                peer=types.InputNotifyPeer(input_peer),
                settings=types.InputPeerNotifySettings(
                    show_previews=show_previews,
                    silent=silent,
                    mute_until=until,
                    sound=types.NotificationSoundDefault(),
                ),
            )
        )
        return {"chat_ref": peer_ref(entity), "muted_until": until.isoformat(), "silent": silent}

    @mcp.tool()
    @with_flood_wait
    async def pin_dialog(chat_ref: str) -> dict:
        """Pin a dialog in the Telegram chat list."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await client.get_input_entity(entity)
        await client(functions.messages.ToggleDialogPinRequest(peer=input_peer, pinned=True))
        invalidate_dialog_cache(client)
        return {"chat_ref": peer_ref(entity), "pinned": True}

    @mcp.tool()
    @with_flood_wait
    async def unpin_dialog(chat_ref: str) -> dict:
        """Unpin a dialog in the Telegram chat list."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await client.get_input_entity(entity)
        await client(functions.messages.ToggleDialogPinRequest(peer=input_peer, pinned=False))
        invalidate_dialog_cache(client)
        return {"chat_ref": peer_ref(entity), "pinned": False}

    @mcp.tool()
    @with_flood_wait
    async def mark_dialog_read(chat_ref: str) -> dict:
        """Mark a dialog as read."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.send_read_acknowledge(entity)
        invalidate_dialog_cache(client)
        return {"chat_ref": peer_ref(entity), "marked_read": True}
