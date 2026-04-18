from __future__ import annotations

import os

from telethon import functions, utils as tg_utils

from ..client import disconnect_client, get_client, with_flood_wait
from ..helpers import user_to_dict
from ..safety import require_destructive
from ..session_store import clear_session


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def get_me() -> dict:
        """Return the logged-in Telegram account."""
        client = await get_client()
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Telegram returned no current user.")
        return user_to_dict(me)

    @mcp.tool()
    @with_flood_wait
    async def get_session_info() -> dict:
        """Return local session metadata and account summary."""
        client = await get_client()
        me = await client.get_me()
        session = client.session
        return {
            "account": user_to_dict(me) if me else None,
            "dc_id": getattr(session, "dc_id", None),
            "server_address": getattr(session, "server_address", None),
            "port": getattr(session, "port", None),
            "takeout_id": getattr(session, "takeout_id", None),
            "connected": client.is_connected(),
        }

    @mcp.tool()
    @with_flood_wait
    async def logout(confirm: bool = False) -> dict:
        """Log out from Telegram and clear the persisted session."""
        require_destructive("logout", confirm)
        client = await get_client()
        await client.log_out()
        await disconnect_client()
        cleared = clear_session(master_key=os.getenv("CODEX_TELEGRAM_MASTER_KEY"))
        return {"logged_out": True, "cleared_local_session": cleared}

    @mcp.tool()
    @with_flood_wait
    async def set_username(username: str) -> dict:
        """Set the account username."""
        client = await get_client()
        updated = await client(functions.account.UpdateUsernameRequest(username=username))
        return user_to_dict(updated)

    @mcp.tool()
    @with_flood_wait
    async def set_bio(about: str, first_name: str | None = None, last_name: str | None = None) -> dict:
        """Set the profile bio and optionally update the display name."""
        client = await get_client()
        result = await client(
            functions.account.UpdateProfileRequest(
                first_name=first_name,
                last_name=last_name,
                about=about,
            )
        )
        return {
            "user_ref": f"user:{result.id}",
            "username": result.username,
            "display_name": tg_utils.get_display_name(result),
            "about": about,
        }
