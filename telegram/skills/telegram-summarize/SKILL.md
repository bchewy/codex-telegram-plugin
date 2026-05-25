---
name: telegram-summarize
description: Summarize one or more Telegram chats over a time window. Prefer cache-backed chunk summaries for known chats with broad, old, repeated, or exhaustive windows; use live history only for small recent catch-ups.
---

1. If the chat is unspecified, call `list_dialogs` and have the user pick the relevant dialog(s).
2. Resolve the time window before fetching history. Prefer explicit windows like `today`, `last 24h`, or ISO timestamps.
3. For known chats, prefer cache-backed summaries when the window is broad, old, repeated, or needs to be exhaustive: call `sync_chat_cache` if the chat is missing/stale, then iterate `summarize_chat_history` chunk-by-chunk (`chunk_index` 0..N-1). Summarize each chunk before fetching the next and merge the chunk summaries. Use `get_history` only for small, recent, one-off windows such as “today” or “last 24h”.
4. Group messages by speaker and sequence so the summary follows the conversation, not isolated quotes.
5. Attribute important decisions or claims to the sender when possible.
6. Produce this output shape unless the user asks otherwise:
   - `TL;DR`
   - `Key decisions`
   - `Open questions`
   - `Action items`
   - `Notable quotes`
7. If the user asks to compare multiple chats, keep each chat separate first, then add a cross-chat synthesis section.
