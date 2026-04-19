from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import functools
import time
from typing import ParamSpec, TypeVar

from telethon import TelegramClient, errors, functions
from telethon.sessions import StringSession

from . import __version__
from .session_store import MissingSessionError, load_session

P = ParamSpec("P")
R = TypeVar("R")

_client: TelegramClient | None = None
_client_lock = asyncio.Lock()
_last_client_verify_monotonic = 0.0

CONNECTION_VERIFY_INTERVAL_SECONDS = 30.0
CONNECTION_VERIFY_TIMEOUT_SECONDS = 5.0
DEFAULT_TAKEOUT_KWARGS = {
    "users": True,
    "chats": True,
    "megagroups": True,
    "channels": True,
}


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


async def _discard_client() -> None:
    global _client, _last_client_verify_monotonic

    if _client:
        try:
            await _client.disconnect()
        except Exception:
            pass
    _client = None
    _last_client_verify_monotonic = 0.0


async def _verify_client_connection(client: TelegramClient) -> None:
    global _last_client_verify_monotonic

    if not client.is_connected():
        raise ConnectionError("Telegram client is disconnected.")

    now = time.monotonic()
    if now - _last_client_verify_monotonic < CONNECTION_VERIFY_INTERVAL_SECONDS:
        return

    try:
        await asyncio.wait_for(
            client(functions.help.GetNearestDcRequest()),
            timeout=CONNECTION_VERIFY_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        await _discard_client()
        raise ConnectionError("Telegram connection is stale.") from exc

    _last_client_verify_monotonic = now


async def get_client() -> TelegramClient:
    global _client, _last_client_verify_monotonic

    if _client:
        try:
            await _verify_client_connection(_client)
            return _client
        except ConnectionError:
            pass

    async with _client_lock:
        if _client:
            try:
                await _verify_client_connection(_client)
                return _client
            except ConnectionError:
                pass

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
        _last_client_verify_monotonic = time.monotonic()
        return _client


async def disconnect_client() -> None:
    await _discard_client()


@asynccontextmanager
async def get_history_client(
    *,
    use_takeout: bool = False,
    takeout_kwargs: dict | None = None,
):
    client = await get_client()
    if not use_takeout:
        yield client
        return

    options = dict(DEFAULT_TAKEOUT_KWARGS)
    if takeout_kwargs:
        options.update(takeout_kwargs)

    try:
        async with client.takeout(finalize=False, **options) as takeout:
            yield takeout
    except errors.TakeoutInitDelayError as exc:
        raise RuntimeError(
            "Telegram takeout could not start yet. "
            f"Wait {exc.seconds} seconds and retry."
        ) from exc


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
