from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class EventSource(StrEnum):
    DISCORD_MESSAGE = "discord_message"
    DISCORD_SLASH = "discord_slash"
    DISCORD_COMPONENT = "discord_component"
    DISCORD_ATTACHMENT = "discord_attachment"
    SYSTEM = "system"


class EventKind(StrEnum):
    MESSAGE = "message"
    MENTION = "mention"
    SLASH_COMMAND = "slash_command"
    COMPONENT = "component"
    ATTACHMENT = "attachment"
    SCHEDULED = "scheduled"


@dataclass(frozen=True)
class AttachmentRef:
    attachment_id: str
    filename: str
    content_type: str = ""
    size_bytes: int | None = None
    url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    source: EventSource
    kind: EventKind
    guild_id: str | None
    channel_id: str
    user_id: str
    user_name: str
    text: str = ""
    attachments: tuple[AttachmentRef, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
