# Telegram Plugin Privacy Policy

This plugin runs locally in Codex and uses the Telegram API credentials and user session configured on your machine.

## Data Access

The plugin can read Telegram dialogs, messages, contacts, media metadata, downloaded media, drafts, reactions, polls, and account metadata when you invoke the relevant tools. It can also send messages or change Telegram state when you ask it to use write-capable tools.

## Local Storage

Telegram session data is stored in the operating-system keyring when available. If the keyring is unavailable, the plugin stores an encrypted session file at `~/.config/codex-telegram/session.enc` using `CODEX_TELEGRAM_MASTER_KEY`.

Cached message history is stored locally at `~/.cache/codex-telegram/cache.db` by default. Cache encryption is optional and requires `CODEX_TELEGRAM_CACHE_ENCRYPT=1`, `CODEX_TELEGRAM_MASTER_KEY`, and `pysqlcipher3`.

## Network Use

The plugin talks to Telegram through Telethon and the official Telegram user-account API. It does not send Telegram message contents to a separate plugin-owned backend.

## User Control

You can clear Telegram auth with the plugin logout flow. You can delete the local message cache by removing `~/.cache/codex-telegram/cache.db` and its SQLite WAL/shm sidecar files.

## Limitations

Codex itself may process message content when you ask the assistant to summarize, search, draft, or reason over Telegram data. Review Codex and OpenAI data settings separately from this plugin policy.
