# Telegram Plugin Terms

This plugin is provided as a local personal-productivity tool for use with your own Telegram account.

## Responsibilities

You are responsible for complying with Telegram's terms, local law, and the expectations of the people and groups whose messages you access. Do not use the plugin to scrape, spam, impersonate, harass, or evade Telegram limits.

## Account Credentials

Use your own Telegram API credentials from `my.telegram.org/apps`. Do not share your `api_hash`, Telegram session string, or `CODEX_TELEGRAM_MASTER_KEY`.

## Write Actions

The plugin includes write-capable tools for sending messages, editing profile information, muting or pinning dialogs, managing groups, and deleting or changing Telegram state. Destructive tools require both `CODEX_TELEGRAM_ALLOW_DESTRUCTIVE=1` and `confirm=True`, but you should still review destination chats and message content before asking Codex to send or modify anything.

## No Warranty

The plugin is provided without warranty. Telegram API behavior, rate limits, permissions, and account state can change, so verify important results before relying on them.
