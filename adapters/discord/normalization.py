from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.events import AttachmentRef, CanonicalEvent, EventKind, EventSource


@dataclass(frozen=True)
class DiscordUserSnapshot:
    user_id: str
    user_name: str
    display_name: str = ""


@dataclass(frozen=True)
class DiscordAttachmentSnapshot:
    attachment_id: str
    filename: str
    content_type: str = ""
    size_bytes: int | None = None
    url: str = ""


@dataclass(frozen=True)
class DiscordMessageSnapshot:
    message_id: str
    guild_id: str | None
    channel_id: str
    author: DiscordUserSnapshot
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: tuple[DiscordAttachmentSnapshot, ...] = ()
    mentioned_user_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscordSlashSnapshot:
    interaction_id: str
    guild_id: str | None
    channel_id: str
    user: DiscordUserSnapshot
    command_name: str
    options: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    attachments: tuple[DiscordAttachmentSnapshot, ...] = ()


def message_to_event(message: DiscordMessageSnapshot, *, bot_user_id: str) -> CanonicalEvent:
    mentions_bot = bot_user_id in message.mentioned_user_ids
    text = _strip_bot_mention(message.content, bot_user_id) if mentions_bot else message.content
    return CanonicalEvent(
        event_id=message.message_id,
        source=EventSource.DISCORD_MESSAGE,
        kind=EventKind.MENTION if mentions_bot else EventKind.MESSAGE,
        guild_id=message.guild_id,
        channel_id=message.channel_id,
        user_id=message.author.user_id,
        user_name=message.author.user_name,
        text=text,
        attachments=tuple(_attachment_ref(attachment) for attachment in message.attachments),
        created_at=message.created_at,
        metadata={
            "discord_display_name": message.author.display_name,
            "mentioned_bot": mentions_bot,
        },
    )


def slash_to_event(slash: DiscordSlashSnapshot) -> CanonicalEvent:
    text = _slash_text(slash)
    return CanonicalEvent(
        event_id=slash.interaction_id,
        source=EventSource.DISCORD_SLASH,
        kind=EventKind.SLASH_COMMAND,
        guild_id=slash.guild_id,
        channel_id=slash.channel_id,
        user_id=slash.user.user_id,
        user_name=slash.user.user_name,
        text=text,
        attachments=tuple(_attachment_ref(attachment) for attachment in slash.attachments),
        created_at=slash.created_at,
        metadata={
            "command_name": slash.command_name,
            "discord_display_name": slash.user.display_name,
            "options": slash.options,
        },
    )


def _attachment_ref(attachment: DiscordAttachmentSnapshot) -> AttachmentRef:
    return AttachmentRef(
        attachment_id=attachment.attachment_id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        url=attachment.url,
    )


def _strip_bot_mention(content: str, bot_user_id: str) -> str:
    text = content.replace(f"<@{bot_user_id}>", "")
    text = text.replace(f"<@!{bot_user_id}>", "")
    return " ".join(text.split())


def _slash_text(slash: DiscordSlashSnapshot) -> str:
    syote = slash.options.get("syote")
    if isinstance(syote, str) and syote.strip():
        return syote.strip()
    return f"/{slash.command_name}"

