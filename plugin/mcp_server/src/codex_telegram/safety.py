from __future__ import annotations

import os

DESTRUCTIVE_ENV = "CODEX_TELEGRAM_ALLOW_DESTRUCTIVE"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def destructive_allowed() -> bool:
    value = os.getenv(DESTRUCTIVE_ENV, "")
    return value.strip().casefold() in _TRUE_VALUES


def require_destructive(tool_name: str, confirm: bool) -> None:
    if destructive_allowed() and confirm:
        return
    raise RuntimeError(
        f"Refusing {tool_name}. "
        f"Set {DESTRUCTIVE_ENV}=1 and pass confirm=True."
    )
