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
from .proxy import mtproxy_client_kwargs
from .session_store import MissingSessionError, load_session

P = ParamSpec("P")
R = TypeVar("R")

_client: TelegramClient | None = None
_client_lock = asyncio.Lock()
_last_client_verify_monotonic = 0.0

CONNECTION_VERIFY_INTERVAL_SECONDS = 30.0
CONNECTION_VERIFY_TIMEOUT_SECONDS = 5.0
DIALOG_CACHE_TTL_SECONDS = 60.0
DIALOG_CACHE_ATTR = "_codex_telegram_dialog_cache"
DEFAULT_TAKEOUT_KWARGS = {
    "users": True,
    "chats": True,
    "megagroups": True,
    "channels": True,
}


class TelegramFloodWaitError(RuntimeError):
    """RuntimeError that preserves Telegram FloodWait metadata.

    Subclasses RuntimeError so existing in-process callers can keep working,
    while carrying `seconds`, `tool_name`, and `attempts` as both attributes
    (for `except TelegramFloodWaitError as exc:` consumers) and a parseable
    suffix in the error message — FastMCP stringifies tool exceptions before
    sending them to the client, so structured attrs alone are not visible
    to MCP callers.
    """

    def __init__(self, *, seconds: int, tool_name: str | None = None, attempts: int = 1):
        self.seconds = seconds
        self.tool_name = tool_name
        self.attempts = attempts
        target = tool_name or "this request"
        super().__init__(
            f"Telegram rate limited {target} for {seconds} seconds. "
            "Wait for the flood window to expire and retry. "
            f"[flood_wait_seconds={seconds} tool_name={tool_name or 'unknown'} "
            f"attempts={attempts}]"
        )


async def list_all_dialogs(client) -> list:
    """Return every dialog for the authenticated account.

    Cached on the client instance for `DIALOG_CACHE_TTL_SECONDS` so repeated
    entity resolution and unread scans don't refetch the full list on every
    call. Replaces the previous `get_dialogs(limit=200)` pattern that
    silently truncated power-user accounts.
    """
    cached = getattr(client, DIALOG_CACHE_ATTR, None)
    if cached is not None:
        fetched_at, dialogs = cached
        if time.monotonic() - fetched_at < DIALOG_CACHE_TTL_SECONDS:
            return dialogs

    dialogs = [dialog async for dialog in client.iter_dialogs()]
    setattr(client, DIALOG_CACHE_ATTR, (time.monotonic(), dialogs))
    return dialogs


def invalidate_dialog_cache(client) -> None:
    if hasattr(client, DIALOG_CACHE_ATTR):
        delattr(client, DIALOG_CACHE_ATTR)


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
        **mtproxy_client_kwargs(),
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

    # Capture a local reference: the verify call awaits, and a concurrent
    # caller may discard the global `_client` in the meantime.
    client = _client
    if client:
        try:
            await _verify_client_connection(client)
            return client
        except ConnectionError:
            pass

    async with _client_lock:
        client = _client
        if client:
            try:
                await _verify_client_connection(client)
                return client
            except ConnectionError:
                pass

        try:
            record = load_session()
        except MissingSessionError as exc:
            # Preserve the storage-layer detail: "encrypted session found but
            # no master key" needs a different remediation than "no session".
            raise RuntimeError(f"Telegram is not authenticated. {exc}") from exc

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

    # Telethon raises if a takeout init request is sent while a previous
    # takeout session (opened with finalize=False) is still active. Calling
    # takeout() without scope kwargs reuses the active session instead.
    # Telegram allows one takeout per session, so the active session's scope
    # wins; use end_takeout_session first to start over with a new scope.
    if client.session.takeout_id is not None:
        async with client.takeout(finalize=False) as takeout:
            yield takeout
        return

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
    """Convert propagated FloodWaitErrors into structured TelegramFloodWaitErrors.

    Telethon itself auto-sleeps floods up to its `flood_sleep_threshold`
    (60s by default), so with default settings every error reaching this
    wrapper exceeds `max_sleep_seconds` and is re-raised immediately as a
    structured error. The sleep-and-retry branch only engages when the
    client is configured with a lower threshold.
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        attempts = 0
        while True:
            try:
                return await func(*args, **kwargs)
            except errors.FloodWaitError as exc:
                attempts += 1
                if attempts > 1 or exc.seconds > max_sleep_seconds:
                    raise TelegramFloodWaitError(
                        seconds=exc.seconds,
                        tool_name=func.__name__,
                        attempts=attempts,
                    ) from exc
                await asyncio.sleep(exc.seconds)

    return wrapper
