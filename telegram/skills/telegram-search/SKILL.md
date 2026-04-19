---
name: telegram-search
description: Search Telegram messages by query, dialog, sender, or time window. Use when the user asks to find a message, locate discussion context, or answer a question from past Telegram chats.
---

1. Convert the user’s request into a precise search query and decide whether it should be global or dialog-scoped.
2. Use `search_messages_in_chat` when the target dialog is known; otherwise use `search_messages_global`.
3. For exhaustive results in a large or long-lived chat, call `sync_chat_cache` first and then use `search_cache`. Keep `search_messages_in_chat` / `search_messages_global` for narrow or recent lookups.
4. Narrow with `from_user`, `min_date`, and `max_date` whenever the user gives enough context.
5. Return the best matches first with:
   - short relevance note
   - sender
   - date
   - chat name
   - message snippet
6. If the user’s request is ambiguous, show the top plausible matches instead of pretending there was one obvious answer.
7. If the user wants the surrounding thread, use `get_message_context` first. Fall back to `get_history` only when they need a wider window than the local context tool returns.
