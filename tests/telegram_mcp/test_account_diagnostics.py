from __future__ import annotations

import asyncio

from codex_telegram.tools import account


class _FakeMCP:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _tool_from(name: str):
    mcp = _FakeMCP()
    account.register(mcp)
    return mcp.tools[name]


def test_telegram_diagnostics_reports_runtime_storage_and_plaintext_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.db"
    cache_path.write_text("cached messages", encoding="utf-8")

    monkeypatch.setattr(account, "cache_db_path", lambda: cache_path)
    monkeypatch.setattr(account, "cache_encryption_enabled", lambda: False)
    monkeypatch.setattr(
        account,
        "describe_storage",
        lambda: {
            "service_name": "codex-telegram-plugin",
            "keyring_session_present": True,
            "encrypted_file_exists": False,
            "session_file": str(tmp_path / "session.enc"),
        },
    )

    result = asyncio.run(_tool_from("telegram_diagnostics")())

    assert result["runtime"]["package_version"] == account.__version__
    assert result["session_storage"]["keyring_session_present"] is True
    assert result["cache"]["path"] == str(cache_path)
    assert result["cache"]["exists"] is True
    assert result["cache"]["encryption_enabled"] is False
    assert result["cache"]["warnings"]


def test_telegram_diagnostics_can_report_auth_error(monkeypatch, tmp_path):
    monkeypatch.setattr(account, "cache_db_path", lambda: tmp_path / "missing.db")
    monkeypatch.setattr(account, "cache_encryption_enabled", lambda: True)
    monkeypatch.setattr(account, "describe_storage", lambda: {})

    async def fake_get_client():
        raise RuntimeError("not authenticated")

    monkeypatch.setattr(account, "get_client", fake_get_client)

    result = asyncio.run(_tool_from("telegram_diagnostics")(include_account=True))

    assert result["account_error"] == {
        "type": "RuntimeError",
        "message": "not authenticated",
    }


def test_logout_reports_local_clear_failure_instead_of_raising(monkeypatch):
    calls = {"logged_out": False, "disconnected": False}

    class _Client:
        async def log_out(self):
            calls["logged_out"] = True

    async def fake_get_client():
        return _Client()

    async def fake_disconnect():
        calls["disconnected"] = True

    def fail_clear(master_key=None):
        raise OSError("disk said no")

    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")
    monkeypatch.setattr(account, "get_client", fake_get_client)
    monkeypatch.setattr(account, "disconnect_client", fake_disconnect)
    monkeypatch.setattr(account, "clear_session", fail_clear)

    result = asyncio.run(_tool_from("logout")(confirm=True))

    # The server-side session is already invalidated by this point, so the
    # tool must report the partial failure rather than raise.
    assert calls == {"logged_out": True, "disconnected": True}
    assert result["logged_out"] is True
    assert result["cleared_local_session"] is False
    assert "disk said no" in result["clear_error"]
