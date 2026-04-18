from __future__ import annotations

from telethon import errors, functions, types, utils as tg_utils

from ..client import get_client, with_flood_wait
from ..helpers import entity_kind, get_chat_id, peer_ref, resolve_entity, resolve_input_channel, resolve_input_user, to_iso, user_to_dict
from ..safety import require_destructive


def _summarize_updates(result) -> dict:
    chats = []
    for chat in getattr(result, "chats", []):
        chats.append(
            {
                "chat_ref": peer_ref(chat),
                "id": getattr(chat, "id", None),
                "title": getattr(chat, "title", None),
                "kind": entity_kind(chat),
            }
        )
    users = [user_to_dict(user) for user in getattr(result, "users", []) if isinstance(user, types.User)]
    return {"chats": chats, "users": users}


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def create_group(title: str, user_refs: list[str], ttl_period: int | None = None) -> dict:
        """Create a basic Telegram group."""
        client = await get_client()
        users = [await resolve_input_user(client, ref) for ref in user_refs]
        result = await client(functions.messages.CreateChatRequest(users=users, title=title, ttl_period=ttl_period))
        summary = _summarize_updates(result)
        summary["title"] = title
        return summary

    @mcp.tool()
    @with_flood_wait
    async def create_channel(
        title: str,
        about: str,
        megagroup: bool = True,
        broadcast: bool = False,
        forum: bool = False,
    ) -> dict:
        """Create a channel or supergroup."""
        client = await get_client()
        result = await client(
            functions.channels.CreateChannelRequest(
                title=title,
                about=about,
                megagroup=megagroup,
                broadcast=broadcast,
                forum=forum,
            )
        )
        summary = _summarize_updates(result)
        summary["title"] = title
        summary["about"] = about
        return summary

    @mcp.tool()
    @with_flood_wait
    async def add_member(chat_ref: str, user_ref: str, fwd_limit: int = 10) -> dict:
        """Add a member to a chat/channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        user = await resolve_input_user(client, user_ref)

        if isinstance(entity, types.Chat):
            result = await client(
                functions.messages.AddChatUserRequest(
                    chat_id=get_chat_id(entity),
                    user_id=user,
                    fwd_limit=fwd_limit,
                )
            )
        else:
            channel = await resolve_input_channel(client, chat_ref)
            result = await client(functions.channels.InviteToChannelRequest(channel=channel, users=[user]))

        return {
            "chat_ref": peer_ref(entity),
            "user_ref": user_ref,
            "result": _summarize_updates(result),
        }

    @mcp.tool()
    @with_flood_wait
    async def remove_member(
        chat_ref: str,
        user_ref: str,
        revoke_history: bool = False,
        confirm: bool = False,
    ) -> dict:
        """Remove a member from a chat/channel."""
        require_destructive("remove_member", confirm)
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        user_entity = await resolve_entity(client, user_ref)

        if isinstance(entity, types.Chat):
            user = await resolve_input_user(client, user_ref)
            result = await client(
                functions.messages.DeleteChatUserRequest(
                    chat_id=get_chat_id(entity),
                    user_id=user,
                    revoke_history=revoke_history,
                )
            )
            payload = _summarize_updates(result)
        else:
            result = await client.kick_participant(entity, user_entity)
            payload = {"kicked_until": to_iso(getattr(result, "date", None))}

        return {
            "chat_ref": peer_ref(entity),
            "user_ref": peer_ref(user_entity),
            "result": payload,
        }

    @mcp.tool()
    @with_flood_wait
    async def promote_admin(
        chat_ref: str,
        user_ref: str,
        title: str | None = None,
        change_info: bool | None = True,
        post_messages: bool | None = None,
        edit_messages: bool | None = None,
        delete_messages: bool | None = True,
        ban_users: bool | None = True,
        invite_users: bool | None = True,
        pin_messages: bool | None = True,
        add_admins: bool | None = None,
        manage_call: bool | None = None,
        anonymous: bool | None = None,
    ) -> dict:
        """Promote a user to admin in a supergroup/channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        user = await resolve_entity(client, user_ref)
        await client.edit_admin(
            entity,
            user,
            change_info=change_info,
            post_messages=post_messages,
            edit_messages=edit_messages,
            delete_messages=delete_messages,
            ban_users=ban_users,
            invite_users=invite_users,
            pin_messages=pin_messages,
            add_admins=add_admins,
            manage_call=manage_call,
            anonymous=anonymous,
            is_admin=True,
            title=title,
        )
        return {"chat_ref": peer_ref(entity), "user_ref": peer_ref(user), "promoted": True, "title": title}

    @mcp.tool()
    @with_flood_wait
    async def demote_admin(chat_ref: str, user_ref: str, confirm: bool = False) -> dict:
        """Remove admin rights from a user."""
        require_destructive("demote_admin", confirm)
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        user = await resolve_entity(client, user_ref)
        await client.edit_admin(entity, user, is_admin=False, title="")
        return {"chat_ref": peer_ref(entity), "user_ref": peer_ref(user), "promoted": False}

    @mcp.tool()
    @with_flood_wait
    async def set_chat_title(chat_ref: str, title: str) -> dict:
        """Rename a group or channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        if isinstance(entity, types.Chat):
            await client(functions.messages.EditChatTitleRequest(chat_id=get_chat_id(entity), title=title))
        else:
            channel = await resolve_input_channel(client, chat_ref)
            await client(functions.channels.EditTitleRequest(channel=channel, title=title))
        return {"chat_ref": peer_ref(entity), "title": title}

    @mcp.tool()
    @with_flood_wait
    async def set_chat_about(chat_ref: str, about: str) -> dict:
        """Set the group/channel description."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await client.get_input_entity(entity)
        await client(functions.messages.EditChatAboutRequest(peer=input_peer, about=about))
        return {"chat_ref": peer_ref(entity), "about": about}

    @mcp.tool()
    @with_flood_wait
    async def leave_chat(chat_ref: str, confirm: bool = False) -> dict:
        """Leave a chat/channel."""
        require_destructive("leave_chat", confirm)
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        await client.delete_dialog(entity)
        return {"chat_ref": peer_ref(entity), "left": True}

    @mcp.tool()
    @with_flood_wait
    async def delete_chat(chat_ref: str, confirm: bool = False) -> dict:
        """Delete a chat/channel if the account has permission, otherwise leave it."""
        require_destructive("delete_chat", confirm)
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        deleted = False
        fell_back_to_leave = False
        fallback_succeeded = False
        error: str | None = None

        try:
            if isinstance(entity, types.Chat):
                await client(functions.messages.DeleteChatRequest(chat_id=get_chat_id(entity)))
            else:
                channel = await resolve_input_channel(client, chat_ref)
                await client(functions.channels.DeleteChannelRequest(channel=channel))
            deleted = True
        except (errors.RPCError, ValueError) as exc:
            fell_back_to_leave = True
            error = f"{type(exc).__name__}: {exc}"
            try:
                await client.delete_dialog(entity)
                fallback_succeeded = True
            except Exception as inner:
                error = f"{error}; fallback failed: {type(inner).__name__}: {inner}"

        return {
            "chat_ref": peer_ref(entity),
            "deleted": deleted,
            "fell_back_to_leave": fell_back_to_leave,
            "fallback_succeeded": fallback_succeeded,
            "error": error,
        }

    @mcp.tool()
    @with_flood_wait
    async def get_members(chat_ref: str, limit: int = 200, search: str = "") -> dict:
        """List members in a group/channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        participants = await client.get_participants(entity, limit=limit, search=search)
        return {
            "chat_ref": peer_ref(entity),
            "count": len(participants),
            "members": [user_to_dict(user) for user in participants if isinstance(user, types.User)],
        }

    @mcp.tool()
    @with_flood_wait
    async def get_admins(chat_ref: str, limit: int = 100) -> dict:
        """List admins in a group/channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)

        if isinstance(entity, types.Chat):
            participants = await client.get_participants(entity, limit=limit)
            admins = []
            for user in participants:
                permissions = await client.get_permissions(entity, user)
                if permissions and permissions.is_admin:
                    admins.append(user_to_dict(user))
        else:
            admins_raw = await client.get_participants(
                entity,
                limit=limit,
                filter=types.ChannelParticipantsAdmins(),
            )
            admins = [user_to_dict(user) for user in admins_raw if isinstance(user, types.User)]

        return {"chat_ref": peer_ref(entity), "count": len(admins), "admins": admins}
