---
name: telegram-aggregate
description: Use when cached Telegram volume or sender stats are requested.
---

1. Resolve the target dialog and time window first; aggregates require a dialog-scoped cache.
2. Check `cache_status` when cache coverage or freshness is unclear. If the chat is missing or stale for the user’s task, call `sync_chat_cache` to incrementally refresh it. Use `full=True` only when the user explicitly asks to rebuild the cache.
3. Use `aggregate_cache` with the right `group_by`:
   - `day` for daily volume
   - `week` for weekly trends
   - `sender` for participation breakdowns
4. If the user wants drill-down after seeing a spike or bucket, use `search_cache` with the same `chat_ref` plus the bucket’s date/sender filters; include `auto_sync_seconds` only if freshness matters.
5. Return the result as concise stats first, then add interpretation:
   - top buckets or top senders
   - notable spikes/drops
   - any obvious caveats (for example partial cache coverage)
