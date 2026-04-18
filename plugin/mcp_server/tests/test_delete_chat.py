from __future__ import annotations

import asyncio

import pytest

from codex_telegram.tools import groups


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _FakeChat:
    id = 1


class _DeleteClient:
    def __init__(self, *, delete_error: Exception | None = None, fallback_error: Exception | None = None):
        self.delete_error = delete_error
        self.fallback_error = fallback_error

    async def __call__(self, _request):
        if self.delete_error is not None:
            raise self.delete_error

    async def delete_dialog(self, _entity):
        if self.fallback_error is not None:
            raise self.fallback_error


def _async_value(value):
    async def inner(*_args, **_kwargs):
        return value

    return inner


def _delete_chat_tool():
    mcp = _FakeMCP()
    groups.register(mcp)
    return mcp.tools["delete_chat"]


def test_delete_chat_reports_direct_delete_success(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setattr(groups, "get_client", _async_value(_DeleteClient()))
    monkeypatch.setattr(groups, "resolve_entity", _async_value(_FakeChat()))
    monkeypatch.setattr(groups, "get_chat_id", lambda entity: entity.id)
    monkeypatch.setattr(groups, "peer_ref", lambda entity: f"chat:{entity.id}")
    monkeypatch.setattr(groups.types, "Chat", _FakeChat)

    result = asyncio.run(_delete_chat_tool()(chat_ref="chat:1", confirm=True))

    assert result == {
        "chat_ref": "chat:1",
        "deleted": True,
        "fell_back_to_leave": False,
        "fallback_succeeded": False,
        "error": None,
    }


def test_delete_chat_reports_fallback_success(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setattr(
        groups,
        "get_client",
        _async_value(_DeleteClient(delete_error=ValueError("cannot delete"))),
    )
    monkeypatch.setattr(groups, "resolve_entity", _async_value(_FakeChat()))
    monkeypatch.setattr(groups, "get_chat_id", lambda entity: entity.id)
    monkeypatch.setattr(groups, "peer_ref", lambda entity: f"chat:{entity.id}")
    monkeypatch.setattr(groups.types, "Chat", _FakeChat)

    result = asyncio.run(_delete_chat_tool()(chat_ref="chat:1", confirm=True))

    assert result["deleted"] is False
    assert result["fell_back_to_leave"] is True
    assert result["fallback_succeeded"] is True
    assert "ValueError" in result["error"]


def test_delete_chat_reports_fallback_failure(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setattr(
        groups,
        "get_client",
        _async_value(
            _DeleteClient(
            delete_error=ValueError("cannot delete"),
            fallback_error=RuntimeError("cannot leave"),
            )
        ),
    )
    monkeypatch.setattr(groups, "resolve_entity", _async_value(_FakeChat()))
    monkeypatch.setattr(groups, "get_chat_id", lambda entity: entity.id)
    monkeypatch.setattr(groups, "peer_ref", lambda entity: f"chat:{entity.id}")
    monkeypatch.setattr(groups.types, "Chat", _FakeChat)

    result = asyncio.run(_delete_chat_tool()(chat_ref="chat:1", confirm=True))

    assert result["deleted"] is False
    assert result["fell_back_to_leave"] is True
    assert result["fallback_succeeded"] is False
    assert "fallback failed" in result["error"]


def test_delete_chat_propagates_unhandled_transport_errors(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setattr(
        groups,
        "get_client",
        _async_value(_DeleteClient(delete_error=RuntimeError("transport"))),
    )
    monkeypatch.setattr(groups, "resolve_entity", _async_value(_FakeChat()))
    monkeypatch.setattr(groups, "get_chat_id", lambda entity: entity.id)
    monkeypatch.setattr(groups, "peer_ref", lambda entity: f"chat:{entity.id}")
    monkeypatch.setattr(groups.types, "Chat", _FakeChat)

    with pytest.raises(RuntimeError, match="transport"):
        asyncio.run(_delete_chat_tool()(chat_ref="chat:1", confirm=True))
