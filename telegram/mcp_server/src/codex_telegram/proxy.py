"""Optional MTProxy transport configured entirely through environment variables.

Some networks (notably hosted agent sandboxes) block direct Telegram MTProto
connections. Telethon can route through an MTProxy instead; setting the three
``TELEGRAM_MTPROXY_*`` variables below switches every client built by this
package onto that proxy without any code or config-file changes. When none of
them are set, connections stay direct and behavior is unchanged.
"""

from __future__ import annotations

import os
from typing import Any

from telethon import connection as tg_connection

MTPROXY_HOST_ENV = "TELEGRAM_MTPROXY_HOST"
MTPROXY_PORT_ENV = "TELEGRAM_MTPROXY_PORT"
MTPROXY_SECRET_ENV = "TELEGRAM_MTPROXY_SECRET"


def mtproxy_client_kwargs() -> dict[str, Any]:
    """Return extra ``TelegramClient`` kwargs when an MTProxy is configured.

    All three variables must be set together. A partial configuration raises
    instead of silently falling back to a direct connection, because the whole
    point of setting them is that the direct path does not work.
    """
    host = os.environ.get(MTPROXY_HOST_ENV, "").strip()
    port_raw = os.environ.get(MTPROXY_PORT_ENV, "").strip()
    secret = os.environ.get(MTPROXY_SECRET_ENV, "").strip()

    if not (host or port_raw or secret):
        return {}

    if not (host and port_raw and secret):
        raise ValueError(
            f"{MTPROXY_HOST_ENV}, {MTPROXY_PORT_ENV}, and {MTPROXY_SECRET_ENV} "
            "must all be set together to route Telegram through an MTProxy."
        )

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError(
            f"{MTPROXY_PORT_ENV} must be an integer port, got {port_raw!r}"
        ) from exc

    return {
        "connection": tg_connection.ConnectionTcpMTProxyRandomizedIntermediate,
        "proxy": (host, port, secret),
    }
