from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

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


class _DialogIteratorClient:
    def __init__(self, dialogs):
        self._dialogs = dialogs
        self.iter_calls = 0

    async def iter_dialogs(self):
        self.iter_calls += 1
        for dialog in self._dialogs:
            yield dialog


def test_list_all_dialogs_caches_per_client(monkeypatch):
    monotonic_time = [1000.0]
    monkeypatch.setattr(client.time, "monotonic", lambda: monotonic_time[0])

    fake = _DialogIteratorClient([SimpleNamespace(title="One"), SimpleNamespace(title="Two")])

    first = asyncio.run(client.list_all_dialogs(fake))
    second = asyncio.run(client.list_all_dialogs(fake))

    assert first == second
    assert [item.title for item in first] == ["One", "Two"]
    assert fake.iter_calls == 1

    monotonic_time[0] += client.DIALOG_CACHE_TTL_SECONDS + 1
    asyncio.run(client.list_all_dialogs(fake))
    assert fake.iter_calls == 2


def test_list_all_dialogs_caches_separately_per_client():
    client_a = _DialogIteratorClient([SimpleNamespace(title="A")])
    client_b = _DialogIteratorClient([SimpleNamespace(title="B")])

    result_a = asyncio.run(client.list_all_dialogs(client_a))
    result_b = asyncio.run(client.list_all_dialogs(client_b))

    assert [item.title for item in result_a] == ["A"]
    assert [item.title for item in result_b] == ["B"]
    assert client_a.iter_calls == 1
    assert client_b.iter_calls == 1


def test_invalidate_dialog_cache_clears_cached_value():
    fake = _DialogIteratorClient([SimpleNamespace(title="One")])

    asyncio.run(client.list_all_dialogs(fake))
    assert fake.iter_calls == 1

    client.invalidate_dialog_cache(fake)
    asyncio.run(client.list_all_dialogs(fake))
    assert fake.iter_calls == 2


def test_with_flood_wait_raises_typed_error_after_retry(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(client.asyncio, "sleep", no_sleep)

    class _StubFloodWait(Exception):
        def __init__(self, seconds):
            self.seconds = seconds
            super().__init__(f"wait {seconds}")

    monkeypatch.setattr(client.errors, "FloodWaitError", _StubFloodWait)

    async def always_flood():
        raise _StubFloodWait(7)

    wrapped = client.with_flood_wait(always_flood)
    with pytest.raises(client.TelegramFloodWaitError) as captured:
        asyncio.run(wrapped())

    err = captured.value
    assert err.seconds == 7
    assert err.tool_name == "always_flood"
    assert err.attempts == 2
    rendered = str(err)
    assert "always_flood" in rendered
    assert "flood_wait_seconds=7" in rendered
    assert "tool_name=always_flood" in rendered
    assert "attempts=2" in rendered


def test_with_flood_wait_rejects_long_waits_without_retry(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(client.asyncio, "sleep", fake_sleep)

    class _StubFloodWait(Exception):
        def __init__(self, seconds):
            self.seconds = seconds
            super().__init__(f"wait {seconds}")

    monkeypatch.setattr(client.errors, "FloodWaitError", _StubFloodWait)

    async def long_flood():
        raise _StubFloodWait(120)

    wrapped = client.with_flood_wait(long_flood, max_sleep_seconds=60)
    with pytest.raises(client.TelegramFloodWaitError) as captured:
        asyncio.run(wrapped())

    assert captured.value.seconds == 120
    assert captured.value.attempts == 1
    assert slept == []
