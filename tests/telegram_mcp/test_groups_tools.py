from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from telethon import types
from telethon.tl.types import messages as tl_messages

from codex_telegram.tools import groups


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


def _tool_from(name: str):
    mcp = _FakeMCP()
    groups.register(mcp)
    return mcp.tools[name]


def _user(user_id: int, name: str) -> types.User:
    return types.User(id=user_id, first_name=name)


def _chat(chat_id: int, title: str) -> types.Chat:
    return types.Chat(
        id=chat_id,
        title=title,
        photo=types.ChatPhotoEmpty(),
        participants_count=2,
        date=None,
        version=1,
    )


def test_summarize_updates_unwraps_invited_users_wrapper():
    chat = _chat(7, "Launch")
    user = _user(99, "Alice")
    wrapped = tl_messages.InvitedUsers(
        updates=SimpleNamespace(chats=[chat], users=[user]),
        missing_invitees=[
            types.MissingInvitee(user_id=123, premium_required_for_pm=True),
        ],
    )

    summary = groups._summarize_updates(wrapped)

    assert summary["chats"] == [
        {"chat_ref": "chat:7", "id": 7, "title": "Launch", "kind": "chat"}
    ]
    assert [item["user_ref"] for item in summary["users"]] == ["user:99"]
    assert summary["missing_invitees"] == [
        {
            "user_ref": "user:123",
            "premium_would_allow_invite": False,
            "premium_required_for_pm": True,
        }
    ]


def test_summarize_updates_still_handles_plain_updates():
    plain = SimpleNamespace(chats=[_chat(5, "Plain")], users=[])

    summary = groups._summarize_updates(plain)

    assert summary["chats"][0]["chat_ref"] == "chat:5"
    assert "missing_invitees" not in summary


def test_create_group_reports_chats_from_invited_users_result(monkeypatch):
    chat = _chat(11, "New Group")
    result = tl_messages.InvitedUsers(
        updates=SimpleNamespace(chats=[chat], users=[]),
        missing_invitees=[],
    )

    captured: dict = {}

    class _Client:
        async def __call__(self, request):
            captured["request"] = request
            return result

    client = _Client()
    monkeypatch.setattr(groups, "get_client", _async_value(client))
    monkeypatch.setattr(groups, "resolve_input_user", _async_value(SimpleNamespace()))

    response = asyncio.run(
        _tool_from("create_group")(title="New Group", user_refs=["user:99"])
    )

    assert response["title"] == "New Group"
    assert response["chats"][0]["chat_ref"] == "chat:11"
    assert response["missing_invitees"] == []


def test_promote_admin_requires_destructive_gate(monkeypatch):
    monkeypatch.delenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", raising=False)

    with pytest.raises(RuntimeError, match="promote_admin"):
        asyncio.run(
            _tool_from("promote_admin")(chat_ref="chat:1", user_ref="user:2")
        )


def test_get_admins_basic_chat_uses_single_full_chat_request(monkeypatch):
    chat = _chat(7, "Launch")
    creator = _user(1, "Alice")
    admin = _user(2, "Bob")
    member = _user(3, "Carol")

    full = SimpleNamespace(
        full_chat=SimpleNamespace(
            participants=SimpleNamespace(
                participants=[
                    types.ChatParticipantCreator(user_id=1),
                    types.ChatParticipantAdmin(user_id=2, inviter_id=1, date=None),
                    types.ChatParticipant(user_id=3, inviter_id=1, date=None),
                ]
            )
        ),
        users=[creator, admin, member],
    )

    class _Client:
        def __init__(self):
            self.request_count = 0

        async def __call__(self, _request):
            self.request_count += 1
            return full

    client = _Client()
    monkeypatch.setattr(groups, "get_client", _async_value(client))
    monkeypatch.setattr(groups, "resolve_entity", _async_value(chat))

    response = asyncio.run(_tool_from("get_admins")(chat_ref="chat:7"))

    assert client.request_count == 1
    assert response["count"] == 2
    assert sorted(item["user_ref"] for item in response["admins"]) == [
        "user:1",
        "user:2",
    ]
