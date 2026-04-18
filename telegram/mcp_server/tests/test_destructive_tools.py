from __future__ import annotations

import asyncio

import pytest

from codex_telegram.tools import account, contacts, extras, groups, media, messages


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _tool_from(module, name: str):
    mcp = _FakeMCP()
    module.register(mcp)
    return mcp.tools[name]


@pytest.mark.parametrize(
    ("module", "tool_name", "kwargs"),
    [
        (messages, "delete_messages", {"chat_ref": "chat:1", "message_ids": [1], "confirm": False}),
        (groups, "leave_chat", {"chat_ref": "chat:1", "confirm": False}),
        (groups, "delete_chat", {"chat_ref": "chat:1", "confirm": False}),
        (groups, "remove_member", {"chat_ref": "chat:1", "user_ref": "user:1", "confirm": False}),
        (groups, "demote_admin", {"chat_ref": "chat:1", "user_ref": "user:1", "confirm": False}),
        (account, "logout", {"confirm": False}),
        (media, "set_profile_photo", {"file_path": "~/photo.jpg", "confirm": False}),
        (contacts, "delete_contact", {"user_refs": ["user:1"], "confirm": False}),
        (contacts, "block_user", {"user_ref": "user:1", "confirm": False}),
        (contacts, "get_user_phone", {"user_ref": "user:1", "confirm": False}),
        (extras, "cancel_scheduled", {"chat_ref": "chat:1", "confirm": False}),
    ],
)
def test_destructive_tools_require_confirm_and_env(monkeypatch, module, tool_name: str, kwargs: dict):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    tool = _tool_from(module, tool_name)

    with pytest.raises(RuntimeError, match="confirm=True"):
        asyncio.run(tool(**kwargs))
