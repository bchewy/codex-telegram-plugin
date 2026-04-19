---
name: telegram-aggregate
description: Aggregate cached Telegram history by day, week, or sender. Use when the user wants volume trends, participation breakdowns, or quick stats across a group/channel history.
---

1. Resolve the target dialog and time window first.
2. If the chat is not cached yet, call `sync_chat_cache`. If the user needs freshness, sync before aggregating.
3. Use `aggregate_cache` with the right `group_by`:
   - `day` for daily volume
   - `week` for weekly trends
   - `sender` for participation breakdowns
4. If the user wants drill-down after seeing a spike or bucket, follow up with `search_cache` for the exact day/week/sender slice.
5. Return the result as concise stats first, then add interpretation:
   - top buckets or top senders
   - notable spikes/drops
   - any obvious caveats (for example partial cache coverage)
