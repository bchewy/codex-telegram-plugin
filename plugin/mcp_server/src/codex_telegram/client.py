from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import functools
from typing import ParamSpec, TypeVar

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from . import __version__
from .session_store import MissingSessionError, load_session

P = ParamSpec("P")
R = TypeVar("R")

_client: TelegramClient | None = None
_client_lock = asyncio.Lock()


def _build_client(session_string: str, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
        device_model="Codex Telegram Plugin",
        system_version="Codex",
        app_version=__version__,
        lang_code="en",
        system_lang_code="en",
    )


async def get_client() -> TelegramClient:
    global _client

    if _client and _client.is_connected():
        return _client

    async with _client_lock:
        if _client and _client.is_connected():
            return _client

        try:
            record = load_session()
        except MissingSessionError as exc:
            raise RuntimeError(
                "Telegram is not authenticated. Run `python -m codex_telegram login` first."
            ) from exc

        client = _build_client(record.session_string, record.api_id, record.api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                "Stored Telegram session is no longer authorized. "
                "Re-run `python -m codex_telegram login`."
            )

        _client = client
        return _client


async def disconnect_client() -> None:
    global _client
    if _client:
        await _client.disconnect()
        _client = None


def with_flood_wait(
    func: Callable[P, Awaitable[R]], *, max_sleep_seconds: int = 60
) -> Callable[P, Awaitable[R]]:
    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        attempts = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except errors.FloodWaitError as exc:
                attempts += 1
                if attempts > 1 or exc.seconds > max_sleep_seconds:
                    raise RuntimeError(
                        f"Telegram rate limited this request for {exc.seconds} seconds. "
                        "Wait for the flood window to expire and retry."
                    ) from exc
                await asyncio.sleep(exc.seconds)

    return wrapper
