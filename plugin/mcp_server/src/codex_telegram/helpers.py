from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from telethon import TelegramClient, types, utils as tg_utils
from telethon.tl.custom.dialog import Dialog
from telethon.tl.custom.draft import Draft
from telethon.tl.custom.message import Message


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.lower() == "now":
        return utc_now()

    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def coerce_message_ids(value: int | Sequence[int]) -> list[int]:
    if isinstance(value, int):
        return [value]
    return [int(item) for item in value]


def peer_ref(peer: Any) -> str:
    if isinstance(peer, types.User):
        return f"user:{peer.id}"
    if isinstance(peer, types.Chat):
        return f"chat:{peer.id}"
    if isinstance(peer, types.Channel):
        return f"channel:{peer.id}"
    if isinstance(peer, types.PeerUser):
        return f"user:{peer.user_id}"
    if isinstance(peer, types.PeerChat):
        return f"chat:{peer.chat_id}"
    if isinstance(peer, types.PeerChannel):
        return f"channel:{peer.channel_id}"
    if isinstance(peer, types.InputPeerUser):
        return f"user:{peer.user_id}"
    if isinstance(peer, types.InputPeerChat):
        return f"chat:{peer.chat_id}"
    if isinstance(peer, types.InputPeerChannel):
        return f"channel:{peer.channel_id}"
    raise TypeError(f"unsupported peer type: {type(peer)!r}")


def entity_kind(entity: Any) -> str:
    if isinstance(entity, (types.User, types.PeerUser, types.InputPeerUser)):
        return "user"
    if isinstance(entity, (types.Chat, types.PeerChat, types.InputPeerChat)):
        return "chat"
    if isinstance(entity, (types.Channel, types.PeerChannel, types.InputPeerChannel)):
        return "channel"
    return type(entity).__name__.lower()


def ensure_download_dir(path: str | None = None) -> Path:
    target = Path(path).expanduser() if path else Path.home() / "Downloads" / "codex-telegram"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _message_file_info(message: Message) -> dict[str, Any] | None:
    if not message.file:
        return None
    return {
        "name": message.file.name,
        "mime_type": message.file.mime_type,
        "size": message.file.size,
        "duration": getattr(message.file, "duration", None),
        "width": getattr(message.file, "width", None),
        "height": getattr(message.file, "height", None),
        "emoji": getattr(message.file, "emoji", None),
        "title": getattr(message.file, "title", None),
        "performer": getattr(message.file, "performer", None),
    }


def _reaction_summary(message: Message) -> list[dict[str, Any]]:
    if not getattr(message, "reactions", None):
        return []

    results = []
    for reaction_result in message.reactions.results:
        reaction = reaction_result.reaction
        results.append(
            {
                "reaction": getattr(reaction, "emoticon", None)
                or getattr(reaction, "document_id", None),
                "count": reaction_result.count,
                "chosen_order": getattr(reaction_result, "chosen_order", None),
            }
        )
    return results


def message_to_dict(message: Message) -> dict[str, Any]:
    sender = message.sender
    sender_name = tg_utils.get_display_name(sender) if sender else None

    return {
        "id": message.id,
        "chat_ref": peer_ref(message.peer_id) if message.peer_id else None,
        "sender_ref": peer_ref(sender) if sender else None,
        "sender_name": sender_name,
        "date": to_iso(message.date),
        "edit_date": to_iso(message.edit_date),
        "text": message.text or "",
        "raw_text": message.raw_text or "",
        "out": message.out,
        "mentioned": message.mentioned,
        "silent": message.silent,
        "reply_to_message_id": getattr(message.reply_to, "reply_to_msg_id", None),
        "views": getattr(message, "views", None),
        "forwards": getattr(message, "forwards", None),
        "grouped_id": message.grouped_id,
        "media": _message_file_info(message),
        "reactions": _reaction_summary(message),
    }


def user_to_dict(entity: types.User) -> dict[str, Any]:
    return {
        "user_ref": peer_ref(entity),
        "id": entity.id,
        "username": entity.username,
        "phone": entity.phone,
        "display_name": tg_utils.get_display_name(entity),
        "bot": entity.bot,
        "verified": entity.verified,
        "premium": entity.premium,
    }


def dialog_to_dict(dialog: Dialog) -> dict[str, Any]:
    entity = dialog.entity
    data: dict[str, Any] = {
        "chat_ref": peer_ref(entity),
        "id": entity.id,
        "kind": entity_kind(entity),
        "title": dialog.title,
        "display_name": tg_utils.get_display_name(entity),
        "username": getattr(entity, "username", None),
        "phone": getattr(entity, "phone", None),
        "unread_count": dialog.unread_count,
        "unread_mentions_count": dialog.unread_mentions_count,
        "pinned": dialog.pinned,
        "archived": dialog.folder_id == 1,
        "draft": dialog.draft.text if dialog.draft else None,
    }
    if dialog.message:
        data["last_message"] = message_to_dict(dialog.message)
    return data


def draft_to_dict(draft: Draft) -> dict[str, Any]:
    entity = getattr(draft, "entity", None)
    return {
        "chat_ref": peer_ref(entity) if entity else None,
        "date": to_iso(getattr(draft, "date", None)),
        "text": draft.text,
        "link_preview": draft.link_preview,
        "reply_to_message_id": draft.reply_to_msg_id,
    }


async def resolve_entity(client: TelegramClient, ref: str | int | Any) -> Any:
    if hasattr(ref, "SUBCLASS_OF_ID"):
        return ref

    if isinstance(ref, int):
        return await client.get_entity(ref)

    if not isinstance(ref, str):
        return await client.get_entity(ref)

    candidate = ref.strip()
    if not candidate:
        raise ValueError("chat_ref cannot be empty")

    if candidate in {"me", "self", "saved", "saved_messages"}:
        return await client.get_entity("me")

    kind, sep, raw_id = candidate.partition(":")
    if sep and raw_id.lstrip("-").isdigit():
        peer = {
            "user": types.PeerUser(int(raw_id)),
            "chat": types.PeerChat(int(raw_id)),
            "channel": types.PeerChannel(int(raw_id)),
        }.get(kind)
        if peer is not None:
            return await client.get_entity(peer)

    try:
        return await client.get_entity(candidate)
    except Exception:
        dialogs = await client.get_dialogs(limit=200)
        lowered = candidate.casefold()
        exact = next(
            (dialog.entity for dialog in dialogs if (dialog.title or "").casefold() == lowered),
            None,
        )
        if exact is not None:
            return exact
        partial = next(
            (dialog.entity for dialog in dialogs if lowered in (dialog.title or "").casefold()),
            None,
        )
        if partial is not None:
            return partial
        raise ValueError(f"Could not resolve chat/user reference: {candidate}") from None


async def resolve_input_peer(client: TelegramClient, ref: str | int | Any) -> Any:
    entity = await resolve_entity(client, ref)
    return await client.get_input_entity(entity)


async def resolve_input_user(client: TelegramClient, ref: str | int | Any) -> Any:
    entity = await resolve_entity(client, ref)
    return tg_utils.get_input_user(entity)


async def resolve_input_channel(client: TelegramClient, ref: str | int | Any) -> Any:
    entity = await resolve_entity(client, ref)
    return tg_utils.get_input_channel(entity)


def get_chat_id(entity: Any) -> int:
    if isinstance(entity, types.Chat):
        return entity.id
    raise ValueError("This operation only supports basic chats, not channels.")


def iter_message_dicts(messages: Iterable[Message]) -> list[dict[str, Any]]:
    return [message_to_dict(message) for message in messages]
