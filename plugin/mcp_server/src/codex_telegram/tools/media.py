from __future__ import annotations

from pathlib import Path

from telethon import functions

from ..client import get_client, with_flood_wait
from ..helpers import (
    ensure_download_dir,
    message_to_dict,
    parse_datetime,
    peer_ref,
    resolve_entity,
    resolve_upload_path,
)
from ..safety import require_destructive


async def _resolve_message(client, chat_ref: str, message_id: int):
    entity = await resolve_entity(client, chat_ref)
    message = await client.get_messages(entity, ids=message_id)
    if not message:
        raise RuntimeError(f"Message {message_id} was not found in {chat_ref}.")
    return entity, message


def register(mcp) -> None:
    @mcp.tool()
    @with_flood_wait
    async def download_media(
        chat_ref: str,
        message_id: int | None = None,
        output_dir: str | None = None,
        limit: int = 1,
    ) -> dict:
        """Download media from one message or the latest media messages in a chat."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        target_dir = ensure_download_dir(output_dir)

        if message_id is not None:
            _, message = await _resolve_message(client, chat_ref, message_id)
            file_path = await client.download_media(message, file=target_dir)
            return {
                "chat_ref": peer_ref(entity),
                "message_id": message_id,
                "downloaded_to": file_path,
            }

        messages = await client.get_messages(entity, limit=max(limit * 4, limit))
        downloaded = []
        for message in messages:
            if not message.media:
                continue
            file_path = await client.download_media(message, file=target_dir)
            downloaded.append({"message_id": message.id, "path": file_path})
            if len(downloaded) >= limit:
                break
        return {"chat_ref": peer_ref(entity), "downloads": downloaded}

    @mcp.tool()
    @with_flood_wait
    async def download_profile_photo(
        chat_ref: str,
        output_dir: str | None = None,
        download_big: bool = True,
    ) -> dict:
        """Download the profile photo for a user/chat/channel."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        target_dir = ensure_download_dir(output_dir)
        file_path = await client.download_profile_photo(entity, file=target_dir, download_big=download_big)
        return {"chat_ref": peer_ref(entity), "downloaded_to": file_path}

    @mcp.tool()
    @with_flood_wait
    async def send_photo(
        chat_ref: str,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a photo."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            caption=caption,
            reply_to=reply_to,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def send_document(
        chat_ref: str,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        force_document: bool = True,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a document/file."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            caption=caption,
            reply_to=reply_to,
            force_document=force_document,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def send_voice(
        chat_ref: str,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a voice note."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            caption=caption,
            reply_to=reply_to,
            voice_note=True,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def send_video(
        chat_ref: str,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        supports_streaming: bool = True,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a video."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            caption=caption,
            reply_to=reply_to,
            supports_streaming=supports_streaming,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def send_sticker(
        chat_ref: str,
        file_path: str,
        reply_to: int | None = None,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a sticker file."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            reply_to=reply_to,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def send_animation(
        chat_ref: str,
        file_path: str,
        caption: str | None = None,
        reply_to: int | None = None,
        schedule_at: str | None = None,
        silent: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Send a GIF/animation."""
        client = await get_client()
        entity = await resolve_entity(client, chat_ref)
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        message = await client.send_file(
            entity,
            upload_path,
            caption=caption,
            reply_to=reply_to,
            silent=silent,
            schedule=parse_datetime(schedule_at),
        )
        payload = message_to_dict(message)
        if warning:
            payload["upload_warning"] = warning
        return payload

    @mcp.tool()
    @with_flood_wait
    async def get_media_info(chat_ref: str, message_id: int) -> dict:
        """Return media/file metadata for a Telegram message."""
        client = await get_client()
        entity, message = await _resolve_message(client, chat_ref, message_id)
        return {
            "chat_ref": peer_ref(entity),
            "message_id": message_id,
            "message": message_to_dict(message),
        }

    @mcp.tool()
    @with_flood_wait
    async def set_profile_photo(
        file_path: str,
        confirm: bool = False,
        allow_arbitrary_path: bool = False,
    ) -> dict:
        """Upload a new account profile photo."""
        require_destructive("set_profile_photo", confirm)
        client = await get_client()
        upload_path, warning = resolve_upload_path(
            file_path,
            allow_arbitrary_path=allow_arbitrary_path,
        )
        uploaded = await client.upload_file(upload_path)
        result = await client(functions.photos.UploadProfilePhotoRequest(file=uploaded))
        photo = result.photo if hasattr(result, "photo") else None
        payload = {
            "updated": True,
            "photo_id": getattr(photo, "id", None),
        }
        if warning:
            payload["upload_warning"] = warning
        return payload
