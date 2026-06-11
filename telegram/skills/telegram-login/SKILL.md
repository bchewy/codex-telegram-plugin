---
name: telegram-login
description: Use when Telegram auth setup, reset, or diagnostics are requested.
---

1. Explain that Telegram user auth for this plugin happens outside the MCP server because Codex spawns MCP servers headlessly over stdio.
2. Tell the user to generate `api_id` and `api_hash` at `https://my.telegram.org/apps`.
3. Instruct them to run the login command from the plugin checkout root (the directory that contains `mcp_server/`; in a repo checkout that is `telegram/`, in an installed bundle it is `~/.codex/plugins/cache/<marketplace>/telegram/<version>/`):
   `uv run --project ./mcp_server codex-telegram login` — or pass the absolute path, e.g. `uv run --project /path/to/telegram/mcp_server codex-telegram login`, to run it from anywhere.
4. Mention the prompts they will see: API ID, API hash, phone number, login code, and optional 2FA password.
5. If the OS keyring is unavailable, instruct them to rerun and let the login flow prompt for a master key, or set `CODEX_TELEGRAM_MASTER_KEY` in the environment first.
6. Once login succeeds, use `get_session_info` or `get_me` to confirm the account.
7. For diagnostics without valid auth (storage backend, cache state, runtime paths), call the `telegram_diagnostics` tool — it never requires a connected session.
8. If they want to clear auth, run `uv run --project ./mcp_server codex-telegram logout` from the same directory (or use the `logout` MCP tool with `confirm=true` if destructive tools are enabled).
