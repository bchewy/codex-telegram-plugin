from __future__ import annotations

import asyncio
from types import SimpleNamespace

from codex_telegram import client


class _FakeTelegramClient:
    def __init__(self, *, connected: bool = False, authorized: bool = True, ping_error: Exception | None = None):
        self.connected = connected
        self.authorized = authorized
        self.ping_error = ping_error
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.requests = []

    def is_connected(self) -> bool:
        return self.connected

    async def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def __call__(self, request):
        self.requests.append(type(request).__name__)
        if self.ping_error is not None:
            raise self.ping_error
        return SimpleNamespace(ok=True)


def test_get_client_reconnects_when_existing_connection_is_stale(monkeypatch):
    stale_client = _FakeTelegramClient(connected=True, ping_error=OSError("socket closed"))
    fresh_client = _FakeTelegramClient(connected=False)

    monkeypatch.setattr(client, "_client", stale_client)
    monkeypatch.setattr(client, "_last_client_verify_monotonic", 0.0)
    monkeypatch.setattr(client, "load_session", lambda: SimpleNamespace(session_string="s", api_id=1, api_hash="h"))
    monkeypatch.setattr(client, "_build_client", lambda *_args: fresh_client)
    monkeypatch.setattr(client.time, "monotonic", lambda: 100.0)

    resolved = asyncio.run(client.get_client())

    assert resolved is fresh_client
    assert stale_client.disconnect_calls == 1
    assert fresh_client.connect_calls == 1


def test_get_client_reuses_recent_verified_connection(monkeypatch):
    healthy_client = _FakeTelegramClient(connected=True)

    monkeypatch.setattr(client, "_client", healthy_client)
    monkeypatch.setattr(client, "_last_client_verify_monotonic", 100.0)
    monkeypatch.setattr(client.time, "monotonic", lambda: 105.0)

    resolved = asyncio.run(client.get_client())

    assert resolved is healthy_client
    assert healthy_client.requests == []
