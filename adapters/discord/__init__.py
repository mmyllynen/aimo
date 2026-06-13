"""Discord adapter shell without runtime Discord dependencies."""

from adapters.discord.normalization import (
    DiscordAttachmentSnapshot,
    DiscordMessageSnapshot,
    DiscordSlashSnapshot,
    DiscordUserSnapshot,
    message_to_event,
    slash_to_event,
)
from adapters.discord.outgoing import DiscordOutbound, OutboundCollector, outgoing_to_discord

__all__ = [
    "DiscordAttachmentSnapshot",
    "DiscordMessageSnapshot",
    "DiscordOutbound",
    "DiscordSlashSnapshot",
    "DiscordUserSnapshot",
    "OutboundCollector",
    "message_to_event",
    "outgoing_to_discord",
    "slash_to_event",
]

