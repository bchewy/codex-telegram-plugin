# Codex Telegram Plugin

Telethon-powered Telegram plugin for Codex that lets a user connect their personal Telegram account, summarize chats, search history, send replies, manage groups, and work through higher-level skills like unread triage.

## What this repo contains

- `mcp_server/`: the Python package and MCP server implementation
- `skills/`: bundled Codex skills (`telegram-summarize`, `telegram-search`, etc.)
- `.codex-plugin/plugin.json`: plugin manifest
- `.mcp.json`: bundled MCP server declaration
- `.agents/plugins/marketplace.json`: local marketplace entry
- `plugin/`: self-contained plugin bundle used by the marketplace entry

## Capabilities

- Read:
  - list dialogs
  - fetch history and unread messages
  - search messages globally or inside one chat
  - inspect media, drafts, members, admins, and account state
- Write:
  - send, reply, edit, delete, forward, pin, and schedule messages
  - send photos, documents, voice notes, videos, stickers, and GIFs
  - save/clear drafts
  - react to messages
  - create polls and vote in them
- Admin:
  - create groups/channels
  - add/remove members
  - promote/demote admins
  - update titles/about text
  - leave/delete chats

The MCP server currently registers 65 tools.

## Requirements

- Python 3.11+
- `uv`
- a Telegram user account
- your own Telegram `api_id` and `api_hash` from [my.telegram.org/apps](https://my.telegram.org/apps)

## Install in Codex

### Local dev install

From this repo:

```bash
codex marketplace add "$(pwd)"
```

Then start a new Codex session. Depending on your local Codex state:

- open `/plugins` inside Codex and install/enable `Telegram`

You can verify that Codex sees bundled MCP servers with:

```bash
codex mcp list
```

### GitHub install

Once this repo is pushed:

```bash
codex marketplace add bchewy/codex-telegram-plugin
```

Then open `/plugins` and install/enable `Telegram`.

## Authenticate Telegram

This plugin uses user-account MTProto auth, not the Bot API.

Run:

```bash
uv run --project ./mcp_server codex-telegram login
```

You will be prompted for:

1. `api_id`
2. `api_hash`
3. phone number in E.164 format
4. the login code Telegram sends
5. your 2FA password, if enabled

The login flow stores credentials in:

1. the OS keyring, if available
2. otherwise an encrypted file at `~/.config/codex-telegram/session.enc`

If the OS keyring is unavailable, provide a master key:

```bash
uv run --project ./mcp_server codex-telegram login --master-key "your-secret"
```

or export:

```bash
export CODEX_TELEGRAM_MASTER_KEY="your-secret"
```

## Useful local commands

```bash
# show storage status
uv run --project ./mcp_server codex-telegram storage

# inspect the authenticated account
uv run --project ./mcp_server codex-telegram whoami

# run tests
uv run --project ./mcp_server pytest

# run the MCP server manually over stdio
uv run --project ./mcp_server codex-telegram serve
```

## Bundled skills

- `telegram-login`
- `telegram-summarize`
- `telegram-triage-unread`
- `telegram-search`
- `telegram-send`
- `telegram-manage-groups`

Use them from Codex with `$telegram-summarize`, `$telegram-search`, etc.

## Security and Telegram-specific caveats

- This is a user-account integration. The stored `StringSession` is effectively full account access.
- If you think the session leaked, revoke it from an official Telegram client immediately.
- Telegram can rate-limit or restrict accounts using third-party clients aggressively. Read-only summarization of your own chats is the lowest-risk path; spammy automation is not.
- QR login is intentionally not implemented here because it has a worse safety profile for userbot-style clients.
- The plugin expects the user to provide their own `api_id` and `api_hash` instead of shipping a shared app credential.

## Troubleshooting

### `FLOOD_WAIT_X`

Telegram is rate-limiting the action. The server retries short waits automatically. Longer waits surface as tool errors.

### `PEER_FLOOD`

Telegram has restricted the account for spammy behavior. This is an account-level issue, not a plugin bug.

### `codex-telegram storage` says no session found

Run:

```bash
uv run --project ./mcp_server codex-telegram login
```

### Plugin MCP server does not appear in Codex settings UI

Known Codex behavior: plugin-bundled MCP servers may not appear in settings even when they are available at runtime. Verify with:

```bash
codex mcp list
```

### Keyring issues

If the OS keyring fails, rerun login with `--master-key` or set `CODEX_TELEGRAM_MASTER_KEY`.

## Development notes

- Source-of-truth development happens in the repo root.
- `plugin/` is the installable bundle that the local marketplace points at.
- After changing manifests, skills, assets, or `mcp_server/`, sync `plugin/` before shipping.

## Test status

Current automated coverage is intentionally focused on the non-network pieces:

- CLI parsing
- helper parsing/ID normalization
- keyring/encrypted-file session storage

Live Telegram smoke tests still require a real authenticated account.
