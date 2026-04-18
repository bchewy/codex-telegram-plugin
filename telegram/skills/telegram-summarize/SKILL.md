---
name: telegram-summarize
description: Summarize one or more Telegram chats over a time window. Use when the user asks to catch up on, recap, summarize, or extract decisions/action items from Telegram threads, groups, or channels.
---

1. If the chat is unspecified, call `list_dialogs` and have the user pick the relevant dialog(s).
2. Resolve the time window before fetching history. Prefer explicit windows like `today`, `last 24h`, or ISO timestamps.
3. Call `get_history` for each target dialog. If the history is large, pull chunks and summarize chunk-by-chunk before merging.
4. Group messages by speaker and sequence so the summary follows the conversation, not isolated quotes.
5. Attribute important decisions or claims to the sender when possible.
6. Produce this output shape unless the user asks otherwise:
   - `TL;DR`
   - `Key decisions`
   - `Open questions`
   - `Action items`
   - `Notable quotes`
7. If the user asks to compare multiple chats, keep each chat separate first, then add a cross-chat synthesis section.
