# Codex Telegram Plugin

Use your personal Telegram account inside Codex.

This plugin lets Codex:

- summarize chats
- search message history
- draft and send replies
- triage unread threads
- manage groups/channels
- work with media, drafts, reactions, polls, and scheduled messages
<img width="878" height="1071" alt="image" src="https://github.com/user-attachments/assets/6f6322b8-253b-458a-8bc2-cf7e5ed62932" />



## Fast setup

If you just want the shortest path, do this:

1. Install the plugin into Codex
2. Create Telegram API credentials at `my.telegram.org/apps`
3. Run the login wizard once
4. Start a fresh Codex thread and use `@Telegram`

The exact commands are below.

## Requirements

- Codex CLI / Codex app
- Python 3.11+
- `uv`
- a real Telegram user account
- your own Telegram `api_id` and `api_hash`

## Step 1: Install the plugin in Codex

### Option A: install from this repo checkout

If you cloned this repo locally:

```bash
cd /path/to/codex-telegram-plugin
codex marketplace add "$(pwd)"
```

Then open a fresh Codex session, run `/plugins`, and install `Telegram`.

### Option B: install from GitHub

If you have access to the repo directly from GitHub:

```bash
codex marketplace add bchewy/codex-telegram-plugin
```

Then open a fresh Codex session, run `/plugins`, and install `Telegram`.

## Step 2: Verify the plugin is installed

In Codex:

1. Open `/plugins`
2. Open `Telegram`
3. Make sure it looks like the screenshot above
4. Make sure the bundled skills are enabled

You should see:

- `Telegram Login`
- `Telegram Summarize`
- `Telegram Triage Unread`
- `Telegram Search`
- `Telegram Send`
- `Telegram Manage Groups`
- bundled MCP server: `telegram_personal`

Important: start a **fresh thread** after installing. Old threads can miss newly installed plugin/skill context.

## Step 3: Create Telegram API credentials

Go to [https://my.telegram.org/apps](https://my.telegram.org/apps)

This is the exact flow:

1. Log in with your phone number
2. Enter the Telegram login code
3. Open `API development tools`
4. Fill the form with something sane, for example:
  - `App title`: `Codex Telegram Plugin`
  - `Short name`: `codextelegramplugin`
  - `Platform`: `Desktop`
  - `URL`: `https://github.com/bchewy/codex-telegram-plugin`
  - `Description`: `Personal Telegram MCP for Codex`
5. Submit
6. Copy:
  - `api_id`
  - `api_hash`

Important:

- this is **not** BotFather
- you want `my.telegram.org/apps`
- the plugin expects **your** API credentials, not a shared developer key

## Step 4: Log in once

This plugin uses Telegram user-account MTProto auth, not the Bot API.

### If you are inside a repo checkout

Run:

```bash
uv run --project ./telegram/mcp_server codex-telegram login
```

### If you already installed the plugin into Codex and just want to authenticate the installed bundle

Run this exact command:

```bash
uv run --project "$(
python3 - <<'PY'
from pathlib import Path

candidates = [
    p for p in Path.home().glob('.codex/plugins/cache/*/telegram/*/mcp_server')
    if p.is_dir()
]
if not candidates:
    raise SystemExit('No installed Telegram plugin bundle found under ~/.codex/plugins/cache')
print(max(candidates, key=lambda p: p.stat().st_mtime))
PY
)" codex-telegram login
```

You will be prompted for:

1. `Telegram API ID`
2. `Telegram API hash`
3. phone number in E.164 format
4. the Telegram login code
5. 2FA password, if your account uses it

Successful output looks like:

```text
{'ok': True, 'storage': 'keyring', 'user_id': 123, 'username': 'yourname', 'display_name': 'Your Name', 'phone': '+15555555555'}
```

## Step 5: Test it in Codex

Start a fresh Codex thread and try one of these:

```text
@Telegram summarize my unread Telegram messages from today
```

```text
@Telegram find Telegram messages from Alice about the launch
```

```text
@Telegram draft a Telegram reply to the design thread
```

Or call the bundled skills directly:

```text
$telegram:telegram-summarize summarize my unread Telegram messages from today
```

```text
$telegram:telegram-search find messages from Alice about launch
```

```text
$telegram:telegram-send draft a reply to the latest message in Saved Messages
```

## Useful commands

### Repo checkout flow

```bash
# show storage status
uv run --project ./telegram/mcp_server codex-telegram storage

# inspect the authenticated account
uv run --project ./telegram/mcp_server codex-telegram whoami

# log out / clear the stored session
uv run --project ./telegram/mcp_server codex-telegram logout

# run tests
uv run --project ./telegram/mcp_server pytest
```

### Installed-bundle flow

```bash
uv run --project "$(
python3 - <<'PY'
from pathlib import Path
candidates = [p for p in Path.home().glob('.codex/plugins/cache/*/telegram/*/mcp_server') if p.is_dir()]
if not candidates:
    raise SystemExit('No installed Telegram plugin bundle found under ~/.codex/plugins/cache')
print(max(candidates, key=lambda p: p.stat().st_mtime))
PY
)" codex-telegram whoami
```

## Bundled skills

Codex registers the skills under the plugin namespace:

- `telegram:telegram-login`
- `telegram:telegram-summarize`
- `telegram:telegram-triage-unread`
- `telegram:telegram-search`
- `telegram:telegram-send`
- `telegram:telegram-manage-groups`

## How sessions are stored

The login wizard stores the Telegram session in:

1. the OS keyring, if available
2. otherwise an encrypted file at `~/.config/codex-telegram/session.enc`

`CODEX_TELEGRAM_SESSION` also exists, but it is intended for test/CI use only. It injects a raw `StringSession` directly and bypasses the normal keyring / encrypted-file flow.

If the OS keyring is unavailable:

```bash
# preferred: let the login flow prompt if keyring is unavailable
uv run --project ./telegram/mcp_server codex-telegram login
```

or:

```bash
read -rsp "Telegram session master key: " CODEX_TELEGRAM_MASTER_KEY; echo
export CODEX_TELEGRAM_MASTER_KEY
uv run --project ./telegram/mcp_server codex-telegram login
unset CODEX_TELEGRAM_MASTER_KEY
```

Do not pass the master key as a CLI flag. It ends up in shell history and `ps`.

## Environment variables


| Variable                           | Purpose                                                                                                                                       |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `TG_API_ID`                        | Telegram API ID used for login/session bootstrap.                                                                                             |
| `TG_API_HASH`                      | Telegram API hash used for login/session bootstrap.                                                                                           |
| `CODEX_TELEGRAM_MASTER_KEY`        | Encrypts/decrypts the fallback session file when the OS keyring is unavailable.                                                               |
| `CODEX_TELEGRAM_SESSION`           | Test/CI-only raw `StringSession` injection. Avoid using this for normal local installs.                                                       |
| `CODEX_TELEGRAM_ALLOW_DESTRUCTIVE` | Must be set to `1` plus `confirm=True` on the tool call before destructive tools like `delete_chat`, `delete_messages`, or `logout` will run. |
| `CODEX_TELEGRAM_UPLOAD_DIR`        | Upload sandbox for `send_*` and `set_profile_photo`. Files outside this directory require `allow_arbitrary_path=True`.                        |


## Troubleshooting

### I installed the plugin but `@Telegram` does not show up

Open a fresh Codex thread first. Plugin and skill context can lag in older threads.

### The plugin page is there, but I am not logged in

Run the login command from Step 4.

### `codex-telegram storage` says no session found

You have not completed the login wizard yet, or you logged in under a different environment/user.

### `FLOOD_WAIT_X`

Telegram is rate-limiting the action. Short waits retry automatically. Longer waits surface as tool errors.

### `PEER_FLOOD`

Telegram restricted the account for spammy behavior. That is an account-level Telegram restriction, not a plugin crash.

### The plugin MCP server does not appear in `codex mcp list`

Do not rely on that alone. Plugin-bundled MCP servers can be present at runtime even if `codex mcp list` is incomplete or another manual MCP server name collides. The stronger checks are:

1. `/plugins` shows `Telegram` installed
2. the plugin page lists `telegram_personal`
3. a fresh thread can use `@Telegram`

### Keyring issues

If the OS keyring fails, rerun login and let it prompt, or pre-set `CODEX_TELEGRAM_MASTER_KEY`.

## What Codex sees

When you invoke a Telegram skill or MCP tool, Codex receives raw chat content and metadata from the response payload. That can include message text, sender names, captions, usernames, reactions, and file metadata.

If you would not paste the content into a Codex prompt directly, do not summarize or process it through this plugin.

## Security / Telegram caveats

- This is a user-account integration. A leaked `StringSession` is effectively full account access.
- If you think the session leaked, revoke it from an official Telegram client immediately.
- Telegram can rate-limit or restrict accounts using aggressive third-party automation.
- Read-only summarization of your own chats is the lowest-risk use case.
- QR login is intentionally not implemented here.

## Repo layout

- `telegram/`: the plugin bundle (single source of truth)
  - `mcp_server/`: Python package and MCP server
  - `skills/`: skill files loaded by the plugin
  - `assets/`: icon, logo, screenshots referenced by the manifest
  - `.codex-plugin/plugin.json`: plugin manifest
  - `.mcp.json`: bundled MCP server declaration
- `.agents/plugins/marketplace.json`: local marketplace definition (points at `./telegram`)
