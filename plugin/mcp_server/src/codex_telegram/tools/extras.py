from __future__ import annotations

import random

from telethon import functions, types

from ..client import get_client, with_flood_wait
from ..helpers import coerce_message_ids, draft_to_dict, message_to_dict, parse_datetime, peer_ref, resolve_entity, resolve_input_peer


def _text_with_entities(value: str) -> types.TextWithEntities:
    return types.TextWithEntities(text=value, entities=[])


def _draft_items(drafts) -> list:
    if isinstance(drafts, list):
        return drafts
    if drafts is None:
        return []
    return [drafts]


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def send_poll(
        chat_ref: str,
        question: str,
        options: list[str],
        message: str = "",
        reply_to: int | None = None,
        multiple_choice: bool = False,
        public_voters: bool = False,
        schedule_at: str | None = None,
        close_at: str | None = None,
    ) -> dict:
        """Send a Telegram poll."""
        if len(options) < 2:
            raise ValueError("A poll needs at least two options.")

        client = await get_client()
        input_peer = await resolve_input_peer(client, chat_ref)
        poll_answers = [
            types.PollAnswer(text=_text_with_entities(option), option=str(index).encode("utf-8"))
            for index, option in enumerate(options)
        ]
        poll = types.Poll(
            id=random.getrandbits(63),
            question=_text_with_entities(question),
            answers=poll_answers,
            hash=0,
            multiple_choice=multiple_choice,
            public_voters=public_voters,
            close_date=parse_datetime(close_at),
        )
        result = await client(
            functions.messages.SendMediaRequest(
                peer=input_peer,
                media=types.InputMediaPoll(poll=poll),
                message=message,
                reply_to=types.InputReplyToMessage(reply_to_msg_id=reply_to) if reply_to else None,
                schedule_date=parse_datetime(schedule_at),
            )
        )
        sent_messages = [update.message for update in getattr(result, "updates", []) if hasattr(update, "message")]
        message_obj = sent_messages[-1] if sent_messages else None
        return {
            "chat_ref": chat_ref,
            "question": question,
            "options": options,
            "message": message_to_dict(message_obj) if message_obj else None,
        }

    @mcp.tool()
    @with_flood_wait
    async def vote_poll(chat_ref: str, message_id: int, option_indices: list[int]) -> dict:
        """Vote in a poll by option index."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        message = await client.get_messages(entity, ids=message_id)
        if not message or not getattr(message.media, "poll", None):
            raise RuntimeError("The target message is not a poll.")

        answers = message.media.poll.answers
        selected = [answers[index].option for index in option_indices]
        await client(functions.messages.SendVoteRequest(peer=input_peer, msg_id=message_id, options=selected))
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "voted_indices": option_indices}

    @mcp.tool()
    @with_flood_wait
    async def close_poll(chat_ref: str, message_id: int) -> dict:
        """Close an open poll."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        message = await client.get_messages(entity, ids=message_id)
        if not message or not getattr(message.media, "poll", None):
            raise RuntimeError("The target message is not a poll.")

        poll = message.media.poll
        closed_poll = types.Poll(
            id=poll.id,
            question=poll.question,
            answers=poll.answers,
            hash=poll.hash,
            closed=True,
            public_voters=poll.public_voters,
            multiple_choice=poll.multiple_choice,
            quiz=poll.quiz,
            close_period=poll.close_period,
            close_date=poll.close_date,
        )
        await client(
            functions.messages.EditMessageRequest(
                peer=input_peer,
                id=message_id,
                media=types.InputMediaPoll(poll=closed_poll),
            )
        )
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "closed": True}

    @mcp.tool()
    @with_flood_wait
    async def add_reaction(chat_ref: str, message_id: int, emoji: str, big: bool = False) -> dict:
        """Add a reaction to a message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        await client(
            functions.messages.SendReactionRequest(
                peer=input_peer,
                msg_id=message_id,
                big=big,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
            )
        )
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "reaction": emoji}

    @mcp.tool()
    @with_flood_wait
    async def remove_reaction(chat_ref: str, message_id: int) -> dict:
        """Remove the account's reaction from a message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        await client(
            functions.messages.SendReactionRequest(
                peer=input_peer,
                msg_id=message_id,
                reaction=[],
            )
        )
        return {"chat_ref": peer_ref(entity), "message_id": message_id, "reaction_removed": True}

    @mcp.tool()
    @with_flood_wait
    async def save_draft(
        chat_ref: str,
        text: str,
        reply_to: int | None = None,
        link_preview: bool = True,
    ) -> dict:
        """Save a draft for a chat."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        await client(
            functions.messages.SaveDraftRequest(
                peer=input_peer,
                message=text,
                no_webpage=not link_preview,
                reply_to=types.InputReplyToMessage(reply_to_msg_id=reply_to) if reply_to else None,
            )
        )
        return {"chat_ref": peer_ref(entity), "draft_saved": True, "text": text}

    @mcp.tool()
    @with_flood_wait
    async def clear_draft(chat_ref: str) -> dict:
        """Clear the draft for a chat."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        await client(functions.messages.SaveDraftRequest(peer=input_peer, message=""))
        return {"chat_ref": peer_ref(entity), "draft_cleared": True}

    @mcp.tool()
    @with_flood_wait
    async def get_drafts(chat_ref: str | None = None) -> dict:
        """List drafts for one chat or across all chats."""
        client = await get_client()
        drafts = await client.get_drafts(await resolve_entity(client, chat_ref) if chat_ref else None)
        items = _draft_items(drafts)
        return {"count": len(items), "drafts": [draft_to_dict(draft) for draft in items]}

    @mcp.tool()
    @with_flood_wait
    async def schedule_message(
        chat_ref: str,
        text: str,
        schedule_at: str,
        reply_to: int | None = None,
        parse_mode: str | None = "md",
    ) -> dict:
        """Schedule a text message."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        message = await client.send_message(
            entity,
            text,
            reply_to=reply_to,
            parse_mode=parse_mode,
            schedule=parse_datetime(schedule_at),
        )
        return message_to_dict(message)

    @mcp.tool()
    @with_flood_wait
    async def cancel_scheduled(chat_ref: str, message_ids: list[int] | None = None) -> dict:
        """Cancel scheduled messages by id, or all scheduled messages in a dialog."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        input_peer = await resolve_input_peer(client, chat_ref)
        ids = message_ids or [message.id for message in await client.get_messages(entity, limit=100, scheduled=True)]
        ids = coerce_message_ids(ids)
        if not ids:
            return {"chat_ref": peer_ref(entity), "cancelled_count": 0}
        await client(functions.messages.DeleteScheduledMessagesRequest(peer=input_peer, id=ids))
        return {"chat_ref": peer_ref(entity), "cancelled_count": len(ids), "message_ids": ids}
