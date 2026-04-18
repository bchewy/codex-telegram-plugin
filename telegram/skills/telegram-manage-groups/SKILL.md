---
name: telegram-manage-groups
description: Manage Telegram groups and channels. Use when the user wants to create chats, add/remove members, promote admins, update titles/about text, or inspect membership.
---

1. Confirm whether the target is a basic group, supergroup, or channel because Telegram permissions differ.
2. Use:
   - `create_group` or `create_channel` for creation
   - `add_member` / `remove_member` for membership changes
   - `promote_admin` / `demote_admin` for role changes
   - `set_chat_title` / `set_chat_about` for metadata updates
   - `get_members` / `get_admins` for inspection
   - `leave_chat` / `delete_chat` for exit/removal flows
3. Restate destructive actions before executing them, especially member removals or deleting/leaving chats.
4. If Telegram rejects the action due to missing admin rights, surface that directly and suggest the smallest next step.
5. After any mutation, summarize the resulting state instead of just saying it succeeded.
