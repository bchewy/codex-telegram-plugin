from __future__ import annotations

import pytest
from telethon import connection as tg_connection
from telethon.sessions import StringSession

from codex_telegram import auth, client
from codex_telegram.proxy import (
    MTPROXY_HOST_ENV,
    MTPROXY_PORT_ENV,
    MTPROXY_SECRET_ENV,
    mtproxy_client_kwargs,
)

SECRET = "dd00000000000000000000000000000000"


def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (MTPROXY_HOST_ENV, MTPROXY_PORT_ENV, MTPROXY_SECRET_ENV):
        monkeypatch.delenv(name, raising=False)


def test_no_env_means_direct_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_proxy_env(monkeypatch)
    assert mtproxy_client_kwargs() == {}


def test_full_env_returns_mtproxy_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv(MTPROXY_HOST_ENV, "proxy.example.com")
    monkeypatch.setenv(MTPROXY_PORT_ENV, "443")
    monkeypatch.setenv(MTPROXY_SECRET_ENV, SECRET)

    kwargs = mtproxy_client_kwargs()

    assert kwargs["connection"] is tg_connection.ConnectionTcpMTProxyRandomizedIntermediate
    assert kwargs["proxy"] == ("proxy.example.com", 443, SECRET)


@pytest.mark.parametrize("missing", [MTPROXY_HOST_ENV, MTPROXY_PORT_ENV, MTPROXY_SECRET_ENV])
def test_partial_env_raises(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    _clear_proxy_env(monkeypatch)
    values = {
        MTPROXY_HOST_ENV: "proxy.example.com",
        MTPROXY_PORT_ENV: "443",
        MTPROXY_SECRET_ENV: SECRET,
    }
    del values[missing]
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="must all be set together"):
        mtproxy_client_kwargs()


def test_non_integer_port_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv(MTPROXY_HOST_ENV, "proxy.example.com")
    monkeypatch.setenv(MTPROXY_PORT_ENV, "https")
    monkeypatch.setenv(MTPROXY_SECRET_ENV, SECRET)

    with pytest.raises(ValueError, match="integer port"):
        mtproxy_client_kwargs()


@pytest.mark.parametrize(
    ("module", "build"),
    [
        (client, lambda: client._build_client("", 123, "hash")),
        (auth, lambda: auth._build_client(StringSession(), 123, "hash")),
    ],
    ids=["client", "auth"],
)
def test_build_client_applies_mtproxy(
    monkeypatch: pytest.MonkeyPatch, module, build
) -> None:
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv(MTPROXY_HOST_ENV, "proxy.example.com")
    monkeypatch.setenv(MTPROXY_PORT_ENV, "443")
    monkeypatch.setenv(MTPROXY_SECRET_ENV, SECRET)

    captured: dict[str, object] = {}

    class _RecordingClient:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(module, "TelegramClient", _RecordingClient)
    build()

    assert captured["connection"] is tg_connection.ConnectionTcpMTProxyRandomizedIntermediate
    assert captured["proxy"] == ("proxy.example.com", 443, SECRET)
