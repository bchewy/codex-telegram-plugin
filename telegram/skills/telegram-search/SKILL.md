---
name: telegram-search
description: Cache-first search for Telegram messages by query, dialog, sender, or time window. Use for finding messages, locating discussion context, or answering questions from past chats; prefer cached search for known dialogs, broad/old windows, repeated searches, or exhaustive results.
---

1. Convert the user’s request into a precise search query, target dialog(s), sender filter, and time window.
2. If the target dialog is known, prefer `search_cache` over live search. Pass `chat_ref`, `query`, `from_user`, `min_date`, `max_date`, `compact=True` for token-efficient result previews, and a freshness window such as `auto_sync_seconds=600` when recent messages may matter.
3. If the target dialog is known but the user explicitly wants a full rebuild, call `sync_chat_cache(chat_ref, full=True)` first. Otherwise rely on incremental sync (`sync_chat_cache(chat_ref)` or `search_cache(chat_ref, ..., auto_sync_seconds=...)`).
4. Use `search_messages_in_chat` only for narrow recent one-off lookups where cache setup is unnecessary. Use `search_messages_global` or `list_dialogs` only when the dialog is unknown, then switch to cached per-dialog search for deeper work.
5. Narrow with `from_user`, `min_date`, `max_date`, and conservative `limit` values whenever the user gives enough context.
6. Return the best matches first with:
   - short relevance note
   - sender
   - date
   - chat name or `chat_ref`
   - message snippet
7. If `search_cache` returns `has_more` / `next_offset`, offer to continue from `next_offset` instead of rerunning the same search.
8. If the user’s request is ambiguous, show the top plausible matches instead of pretending there was one obvious answer.
9. If the user wants surrounding discussion, use thread-aware tools when available; otherwise use `get_message_context` for chronological neighbors and say that it is chronological context, not necessarily the reply/topic thread.
