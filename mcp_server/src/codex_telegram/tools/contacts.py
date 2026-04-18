from __future__ import annotations

from telethon import functions, types, utils as tg_utils

from ..client import get_client, with_flood_wait
from ..helpers import peer_ref, resolve_entity, resolve_input_user, user_to_dict
from ..safety import require_destructive


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def get_contacts(limit: int = 500, query: str | None = None) -> dict:
        """List Telegram contacts."""
        client = await get_client()
        result = await client(functions.contacts.GetContactsRequest(hash=0))
        users = [user for user in result.users if isinstance(user, types.User)]
        if query:
            lowered = query.casefold()
            users = [
                user
                for user in users
                if lowered in tg_utils.get_display_name(user).casefold()
                or lowered in (user.username or "").casefold()
            ]
        users = users[:limit]
        return {"count": len(users), "contacts": [user_to_dict(user) for user in users]}

    @mcp.tool()
    @with_flood_wait
    async def add_contact(
        user_ref: str,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        share_phone_privacy_exception: bool = False,
    ) -> dict:
        """Add a Telegram user to contacts."""
        client = await get_client()
        entity = await resolve_entity(client, user_ref)
        if not isinstance(entity, types.User):
            raise RuntimeError("add_contact requires a user reference, not a chat/channel.")

        input_user = await resolve_input_user(client, user_ref)
        result = await client(
            functions.contacts.AddContactRequest(
                id=input_user,
                first_name=first_name or entity.first_name or entity.username or "Unknown",
                last_name=last_name or entity.last_name or "",
                phone=phone or entity.phone or "",
                add_phone_privacy_exception=share_phone_privacy_exception,
            )
        )
        return {
            "added": True,
            "user_ref": peer_ref(entity),
            "result_users": [user_to_dict(user) for user in result.users if isinstance(user, types.User)],
        }

    @mcp.tool()
    @with_flood_wait
    async def delete_contact(user_refs: list[str], confirm: bool = False) -> dict:
        """Delete one or more contacts."""
        require_destructive("delete_contact", confirm)
        client = await get_client()
        users = [await resolve_input_user(client, user_ref) for user_ref in user_refs]
        result = await client(functions.contacts.DeleteContactsRequest(id=users))
        deleted = [user_to_dict(user) for user in result.users if isinstance(user, types.User)]
        return {"deleted_count": len(deleted), "deleted": deleted}

    @mcp.tool()
    @with_flood_wait
    async def block_user(user_ref: str, confirm: bool = False) -> dict:
        """Block a Telegram user."""
        require_destructive("block_user", confirm)
        client = await get_client()
        input_peer = await client.get_input_entity(await resolve_entity(client, user_ref))
        await client(functions.contacts.BlockRequest(id=input_peer))
        return {"user_ref": user_ref, "blocked": True}

    @mcp.tool()
    @with_flood_wait
    async def get_user_phone(user_ref: str, confirm: bool = False) -> dict:
        """Return the raw phone number for a Telegram user."""
        require_destructive("get_user_phone", confirm)
        client = await get_client()
        entity = await resolve_entity(client, user_ref)
        if not isinstance(entity, types.User):
            raise RuntimeError("get_user_phone requires a user reference, not a chat/channel.")
        return {
            "user_ref": peer_ref(entity),
            "phone": entity.phone,
        }

    @mcp.tool()
    @with_flood_wait
    async def unblock_user(user_ref: str) -> dict:
        """Unblock a Telegram user."""
        client = await get_client()
        input_peer = await client.get_input_entity(await resolve_entity(client, user_ref))
        await client(functions.contacts.UnblockRequest(id=input_peer))
        return {"user_ref": user_ref, "blocked": False}

    @mcp.tool()
    @with_flood_wait
    async def resolve_username(username: str) -> dict:
        """Resolve a @username into a Telegram entity."""
        client = await get_client()
        entity = await resolve_entity(client, username.removeprefix("@"))
        if isinstance(entity, types.User):
            return user_to_dict(entity)
        return {
            "chat_ref": peer_ref(entity),
            "id": getattr(entity, "id", None),
            "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None),
        }
