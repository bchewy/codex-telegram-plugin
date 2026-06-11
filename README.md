# Codex Telegram Plugin

Use your personal Telegram account inside Codex.

This plugin lets Codex:

- summarize chats
- search recent messages live, or search cached chat history for repeat/broad/old lookups
- sync recent chat history into a local cache once, then summarize, search, and aggregate locally to reduce repeated Telegram API calls (see the cache section below — first sync covers the newest N messages; older backfill is not yet exposed)
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

## Codex marketplace model

A Codex marketplace is a catalog of plugins. Its `interface.displayName` is the
dropdown label in Codex, while this plugin's `interface.displayName` is the
installable item shown inside that marketplace.

For a single local selector, keep all local plugin entries in one user-level
marketplace at `~/.agents/plugins/marketplace.json`. Do not keep a repo-local
`.agents/plugins/marketplace.json` active for this checkout unless you
intentionally want Codex to show this repository as a separate marketplace.

This repo's plugin bundle is `telegram/`. In the shared `Local Plugins`
marketplace, the plugin should be installed as:

```bash
codex plugin add telegram@local
```

The matching WhatsApp plugin uses the same model: one `Local Plugins`
marketplace, separate `telegram` and `whatsapp` plugin entries.

For checkouts under `~/dev`, the relevant `plugins` entries look like this.
Preserve any other plugins already present in your local marketplace file.

```json
{
  "name": "local",
  "interface": {
    "displayName": "Local Plugins"
  },
  "plugins": [
    {
      "name": "telegram",
      "source": {
        "source": "local",
        "path": "./dev/codex-telegram-plugin/telegram"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    },
    {
      "name": "whatsapp",
      "source": {
        "source": "local",
        "path": "./dev/codex-whatsapp-plugin/whatsapp"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

## Requirements

- Codex CLI / Codex app
- Python 3.11+
- `uv`
- a real Telegram user account
- your own Telegram `api_id` and `api_hash`

## Step 1: Install the plugin in Codex

This repo is designed to be installed from the shared local marketplace instead
of registering itself as a separate marketplace.

If your `~/.agents/plugins/marketplace.json` already includes this checkout,
install the plugin with:

```bash
codex plugin add telegram@local
```

If the local marketplace does not include it yet, add a `telegram` entry that
points at this repo's `telegram/` directory, then rerun the command above. Keep
the marketplace name as `local` and the display name as `Local Plugins` if you
want it grouped with your other local plugins.

Open a fresh Codex session after installing. Old threads can miss newly
installed plugin, skill, and MCP context.

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
- `Telegram Aggregate`
- `Telegram Send`
- `Telegram Manage Groups`
- `Telegram Media Inspect`
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
@Telegram cache the Design chat, then search it for launch blockers from last month
```

```text
@Telegram draft a Telegram reply to the design thread
```

```text
@Telegram watch this Telegram bubble and transcribe what it says
```

Or call the bundled skills directly:

```text
$telegram:telegram-summarize summarize my unread Telegram messages from today
```

```text
$telegram:telegram-search find messages from Alice about launch
```

```text
$telegram:telegram-aggregate show cached weekly message volume for the Design chat this quarter
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

# run tests (run from telegram/mcp_server so the pytest config and coverage
# settings in its pyproject.toml are picked up; this also writes
# telegram/coverage/coverage.xml for Plugin Eval)
cd telegram/mcp_server && uv run pytest
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
- `telegram:telegram-aggregate`
- `telegram:telegram-media-inspect`
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
| `CODEX_TELEGRAM_CACHE_ENCRYPT`     | Optional: set to `1` to encrypt the local SQLite message cache. Requires `pysqlcipher3` plus `CODEX_TELEGRAM_MASTER_KEY`.                    |
| `CODEX_TELEGRAM_ALLOW_DESTRUCTIVE` | Must be set to `1` plus `confirm=True` on the tool call before destructive tools like `delete_chat`, `delete_messages`, or `logout` will run. |
| `CODEX_TELEGRAM_UPLOAD_DIR`        | Upload sandbox for `send_*` and `set_profile_photo`. Files outside this directory require `allow_arbitrary_path=True`.                        |
| `CODEX_TELEGRAM_CONFIG_DIR`        | Optional: overrides the config directory that stores the encrypted session file (default `~/.config/codex-telegram`).                         |
| `CODEX_TELEGRAM_MEDIA_SCRIPTS_DIR` | Optional: overrides the directory containing the `telegram-media-inspect` scripts used by `inspect_message_media`.                            |
| `XDG_CACHE_HOME`                   | Optional (standard XDG var): changes where the local message cache lives (default `~/.cache/codex-telegram/cache.db`).                        |


## Local cache: use it for broad, old, repeated, or aggregate work

The local SQLite cache lives at `~/.cache/codex-telegram/cache.db` and is per chat.
Use live search for quick recent lookups or when you do not know the dialog yet. Use the cache when the dialog is known and the task is broad, old, repeated, exhaustive, a summary, or an aggregate.

- `cache_status` shows which chats are cached, message counts, and last sync times.
- `sync_chat_cache(chat_ref)` incrementally adds new messages for one chat. Use `full=True` only when you intentionally want to rebuild that chat’s cache. The first sync of a chat bootstraps by iterating messages with `iter_messages(limit=max_messages_per_batch)` (default 5000) — for chats larger than that batch, the response sets `older_history_uncached: true` and exposes `oldest_fetched_id` so callers can detect the cap; older history is not currently backfilled by this tool.
- `search_cache(chat_ref, query, from_user, min_date, max_date, auto_sync_seconds=600, compact=True)` searches locally and can auto-sync the chat first if the cache is missing or stale. Use `compact=True` for token-efficient previews; use `next_offset` to continue paginated results.
- `summarize_chat_history(chat_ref, min_date, max_date, chunk_index=0)` returns SQL-paginated cache-backed chunks for map-reduce summaries.
- `aggregate_cache(chat_ref, min_date, max_date, group_by="day|week|sender")` returns local counts without re-querying Telegram.

For unknown-dialog searches, first use live search or `list_dialogs` to identify candidate chats, then sync/search those chats through the cache.

If you want the cache encrypted at rest, install `pysqlcipher3`, set `CODEX_TELEGRAM_CACHE_ENCRYPT=1`, and provide `CODEX_TELEGRAM_MASTER_KEY`.

## Troubleshooting

### Check runtime, auth, and cache diagnostics

Use the `telegram_diagnostics` MCP tool when the plugin may be running from a stale installed bundle, when auth is unclear, or when you want to verify whether the local message cache is encrypted. It returns the package version, plugin root, session-storage state, cache path, cache size, and cache encryption status without requiring a working Telegram login. Pass `include_account=True` if you also want it to attempt an authenticated account check.

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
- Local marketplace registration lives outside this repo in `~/.agents/plugins/marketplace.json`
