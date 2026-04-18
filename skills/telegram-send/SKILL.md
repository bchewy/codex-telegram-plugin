---
name: telegram-send
description: Draft, refine, schedule, or send Telegram messages. Use when the user wants help replying, sending updates, forwarding messages, or scheduling future sends.
---

1. Understand whether the user wants a draft, a scheduled message, or an immediate send.
2. If the target chat is ambiguous, call `list_dialogs` and confirm the destination before sending.
3. Draft the message in the user’s tone first when quality matters.
4. Use:
   - `send_message` for new messages
   - `reply_message` for threaded replies
   - `forward_messages` for forwarding
   - `schedule_message` for timed delivery
   - `save_draft` when the user wants to review before sending
5. For risky or high-stakes sends, show the final draft and destination back to the user before invoking the write tool.
6. If the user asks to attach media, use the relevant `send_*` media tool instead of forcing everything through text.
