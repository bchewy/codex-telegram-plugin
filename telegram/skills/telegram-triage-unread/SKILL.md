---
name: telegram-triage-unread
description: Use when priority-ranked unread Telegram digests are requested.
---

1. Call `get_unread` without a `chat_ref` to gather unread messages across dialogs.
2. Rank dialogs by urgency using a mix of unread count, sender importance mentioned by the user, explicit deadlines, and message salience.
3. For each dialog, summarize unread content in 1-3 bullets.
4. Separate messages into:
   - `Needs reply`
   - `FYI`
   - `Blocked / decision needed`
   - `Can ignore for now`
5. If a follow-up is obvious, draft a reply but do not send it unless the user asks.
6. If the unread volume is high, summarize per dialog first and then produce a compressed top-priority list.
