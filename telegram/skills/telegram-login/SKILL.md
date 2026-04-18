---
name: telegram-login
description: Use when the user wants to connect, reconnect, inspect, or reset their personal Telegram account for this plugin. Do not use for message retrieval or sending unless auth/setup is the blocker.
---

1. Explain that Telegram user auth for this plugin happens outside the MCP server because Codex spawns MCP servers headlessly over stdio.
2. Tell the user to generate `api_id` and `api_hash` at `https://my.telegram.org/apps`.
3. Instruct them to run `uv run --project ./mcp_server codex-telegram login`.
4. Mention the prompts they will see: API ID, API hash, phone number, login code, and optional 2FA password.
5. If the OS keyring is unavailable, instruct them to rerun and let the login flow prompt for a master key, or set `CODEX_TELEGRAM_MASTER_KEY` in the environment first.
6. Once login succeeds, use `get_session_info` or `get_me` to confirm the account.
7. If they want to clear auth, use `uv run --project ./mcp_server codex-telegram logout`.
