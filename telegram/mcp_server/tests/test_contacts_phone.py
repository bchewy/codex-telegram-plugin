from __future__ import annotations

import asyncio
from types import SimpleNamespace

from codex_telegram.tools import contacts


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _async_value(value):
    async def inner(*_args, **_kwargs):
        return value

    return inner


def test_get_user_phone_returns_raw_phone_when_explicitly_allowed(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")

    mcp = _FakeMCP()
    contacts.register(mcp)
    tool = mcp.tools["get_user_phone"]

    user = SimpleNamespace(id=42, phone="+15555555555")
    monkeypatch.setattr(contacts, "get_client", _async_value(object()))
    monkeypatch.setattr(contacts, "resolve_entity", _async_value(user))
    monkeypatch.setattr(contacts, "peer_ref", lambda entity: f"user:{entity.id}")
    monkeypatch.setattr(contacts.types, "User", user.__class__)

    result = asyncio.run(tool(user_ref="user:42", confirm=True))

    assert result == {
        "user_ref": "user:42",
        "phone": "+15555555555",
    }
