from __future__ import annotations

import argparse
import asyncio
import json

from .auth import login_interactive, whoami_interactive
from .server import run_server
from .session_store import clear_session, describe_storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-telegram",
        description="Telethon-backed Telegram MCP server for Codex.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="Run the MCP server over stdio.")

    login = subparsers.add_parser("login", help="Authenticate a Telegram account.")
    login.add_argument("--api-id", type=int, default=None)
    login.add_argument("--api-hash", default=None)
    login.add_argument("--phone", default=None)
    login.add_argument(
        "--master-key",
        default=None,
        help="Used only if the OS keyring is unavailable and an encrypted file fallback is needed.",
    )

    subparsers.add_parser("whoami", help="Print the currently stored Telegram account.")

    logout = subparsers.add_parser("logout", help="Clear the stored Telegram session.")
    logout.add_argument("--master-key", default=None)

    subparsers.add_parser("storage", help="Describe the current credential storage backend.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "serve":
        run_server()
        return

    if args.command == "login":
        asyncio.run(
            login_interactive(
                api_id=args.api_id,
                api_hash=args.api_hash,
                phone=args.phone,
                master_key=args.master_key,
            )
        )
        return

    if args.command == "whoami":
        asyncio.run(whoami_interactive())
        return

    if args.command == "logout":
        removed = clear_session(master_key=args.master_key)
        print(json.dumps({"logged_out": removed}))
        return

    if args.command == "storage":
        print(json.dumps(describe_storage(), indent=2))
        return

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
