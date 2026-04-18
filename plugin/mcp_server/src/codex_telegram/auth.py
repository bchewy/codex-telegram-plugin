from __future__ import annotations

import getpass
from typing import Any

from telethon import TelegramClient, errors, utils as tg_utils
from telethon.sessions import StringSession

from . import __version__
from .helpers import utc_now
from .models import StoredSession
from .session_store import SessionStoreError, load_session, save_session


def _prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"{label}{suffix}: "
    value = getpass.getpass(prompt) if secret else input(prompt)
    value = value.strip()
    if value:
        return value
    if default is not None:
        return default
    raise ValueError(f"{label} is required")


def _build_client(session: StringSession, api_id: int, api_hash: str) -> TelegramClient:
    return TelegramClient(
        session,
        api_id,
        api_hash,
        device_model="Codex Telegram Plugin",
        system_version="Codex",
        app_version=__version__,
        lang_code="en",
        system_lang_code="en",
    )


async def login_interactive(
    api_id: int | None = None,
    api_hash: str | None = None,
    phone: str | None = None,
    master_key: str | None = None,
) -> dict[str, Any]:
    api_id = api_id or int(_prompt("Telegram API ID"))
    api_hash = api_hash or _prompt("Telegram API hash")
    phone = phone or _prompt("Phone number (E.164, e.g. +15555555555)")

    client = _build_client(StringSession(), api_id, api_hash)
    await client.connect()

    try:
        sent_code = await client.send_code_request(phone)
        code = _prompt("Telegram login code")

        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent_code.phone_code_hash)
        except errors.SessionPasswordNeededError:
            password = _prompt("Telegram 2FA password", secret=True)
            await client.sign_in(password=password)

        me = await client.get_me()
        now = utc_now().isoformat()
        record = StoredSession(
            api_id=api_id,
            api_hash=api_hash,
            session_string=StringSession.save(client.session),
            phone=phone,
            user_id=me.id if me else None,
            username=getattr(me, "username", None),
            display_name=tg_utils.get_display_name(me) if me else None,
            created_at=now,
            updated_at=now,
        )

        backend = save_session(record, master_key=master_key)
        result = {
            "ok": True,
            "storage": backend,
            "user_id": record.user_id,
            "username": record.username,
            "display_name": record.display_name,
            "phone": phone,
        }
        print(result)
        return result
    except (
        errors.ApiIdInvalidError,
        errors.ApiIdPublishedFloodError,
        errors.AuthRestartError,
        errors.PhoneCodeExpiredError,
        errors.PhoneCodeInvalidError,
        errors.PhoneNumberBannedError,
        errors.PhoneNumberInvalidError,
        errors.PhonePasswordFloodError,
        errors.PhonePasswordProtectedError,
        errors.PasswordHashInvalidError,
        errors.FloodWaitError,
        SessionStoreError,
    ) as exc:
        raise RuntimeError(f"Telegram login failed: {exc}") from exc
    finally:
        await client.disconnect()


async def whoami_interactive() -> dict[str, Any]:
    record = load_session()
    client = _build_client(StringSession(record.session_string), record.api_id, record.api_hash)
    await client.connect()
    try:
        me = await client.get_me()
        result = {
            "user_ref": f"user:{me.id}" if me else None,
            "username": getattr(me, "username", None),
            "display_name": tg_utils.get_display_name(me) if me else None,
            "phone": getattr(me, "phone", None),
        }
        print(result)
        return result
    finally:
        await client.disconnect()
