from __future__ import annotations

import pytest

from codex_telegram.safety import require_destructive


def test_require_destructive_rejects_without_env(monkeypatch):
    monkeypatch.delenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", raising=False)

    with pytest.raises(RuntimeError, match="delete_chat"):
        require_destructive("delete_chat", confirm=True)


def test_require_destructive_rejects_without_confirm(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "1")

    with pytest.raises(RuntimeError, match="confirm=True"):
        require_destructive("delete_chat", confirm=False)


def test_require_destructive_allows_when_env_and_confirm_are_set(monkeypatch):
    monkeypatch.setenv("CODEX_TELEGRAM_ALLOW_DESTRUCTIVE", "true")

    require_destructive("delete_chat", confirm=True)
