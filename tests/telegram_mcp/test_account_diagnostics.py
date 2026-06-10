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
