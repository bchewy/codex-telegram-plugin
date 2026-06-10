from __future__ import annotations

import os
from pathlib import Path

from telethon import functions, utils as tg_utils

from .. import __version__
from ..cache import CACHE_ENCRYPT_ENV_VAR, cache_db_path, cache_encryption_enabled
from ..client import disconnect_client, get_client, with_flood_wait
from ..helpers import user_to_dict
from ..safety import require_destructive
from ..session_store import MASTER_KEY_ENV_VAR, clear_session, describe_storage


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _cache_diagnostics() -> dict:
    path = cache_db_path()
    encrypted = cache_encryption_enabled()
    warnings = []
    if path.exists() and not encrypted:
        warnings.append(
            "Telegram message cache exists and is not encrypted. "
            f"Set {CACHE_ENCRYPT_ENV_VAR}=1 with {MASTER_KEY_ENV_VAR} to encrypt future cache access."
        )

    return {
        "path": str(path),
        "exists": path.exists(),
        "db_size_bytes": path.stat().st_size if path.exists() else 0,
        "encryption_enabled": encrypted,
        "encryption_env_var": CACHE_ENCRYPT_ENV_VAR,
        "master_key_env_present": bool(os.getenv(MASTER_KEY_ENV_VAR)),
        "warnings": warnings,
    }


def _runtime_diagnostics() -> dict:
    plugin_root = _plugin_root()
    return {
        "package_version": __version__,
        "plugin_root": str(plugin_root),
        "mcp_server_root": str(plugin_root / "mcp_server"),
    }


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
            "runtime": _runtime_diagnostics(),
            "session_storage": describe_storage(),
            "cache": _cache_diagnostics(),
            "dc_id": getattr(session, "dc_id", None),
            "server_address": getattr(session, "server_address", None),
            "port": getattr(session, "port", None),
            "takeout_id": getattr(session, "takeout_id", None),
            "connected": client.is_connected(),
        }

    @mcp.tool()
    async def telegram_diagnostics(include_account: bool = False) -> dict:
        """Return local runtime, storage, and cache diagnostics without requiring auth."""
        result = {
            "runtime": _runtime_diagnostics(),
            "session_storage": describe_storage(),
            "cache": _cache_diagnostics(),
        }
        if not include_account:
            return result

        try:
            client = await get_client()
            me = await client.get_me()
            result["account"] = user_to_dict(me) if me else None
            result["connected"] = client.is_connected()
        except Exception as exc:
            result["account_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
        return result

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
