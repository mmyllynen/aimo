from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.i18n import Translator
from core.workflows import OutgoingKind, OutgoingMessage


@dataclass(frozen=True)
class DiscordOutbound:
    text: str = ""
    ephemeral: bool = False
    filename: str = ""
    content_type: str = ""
    content: bytes | None = None
    allowed_mentions: dict[str, list[str]] = field(default_factory=lambda: {"parse": []})
    metadata: dict[str, Any] = field(default_factory=dict)


class OutboundCollector:
    def __init__(self) -> None:
        self.sent: list[DiscordOutbound] = []

    def send(self, outbound: DiscordOutbound) -> None:
        self.sent.append(outbound)


def outgoing_to_discord(message: OutgoingMessage, translator: Translator) -> DiscordOutbound:
    return DiscordOutbound(
        text=_render_text(message, translator),
        ephemeral=message.kind in {OutgoingKind.EPHEMERAL_TEXT, OutgoingKind.EPHEMERAL_FILE},
        filename=message.filename,
        content_type=message.content_type,
        content=message.content,
        metadata=message.metadata,
    )


def _render_text(message: OutgoingMessage, translator: Translator) -> str:
    if message.localized_text is not None:
        return _sanitize_broad_mentions(translator.render(message.localized_text))
    if message.text_key:
        return _sanitize_broad_mentions(translator.text(message.text_key, **message.text_params))
    return _sanitize_broad_mentions(message.text)


def _sanitize_broad_mentions(text: str) -> str:
    return text.replace("@everyone", "@ everyone").replace("@here", "@ here")

