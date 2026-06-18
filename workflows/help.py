from __future__ import annotations

from core.events import CanonicalEvent
from core.i18n import LocalizedText, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus


HELP_TOPIC_KEYS = {
    "": TranslationKey.HELP_INTRO,
    "/aimo": TranslationKey.HELP_INTRO,
    "aimo": TranslationKey.HELP_INTRO,
    "/help": TranslationKey.HELP_INTRO,
    "help": TranslationKey.HELP_INTRO,
    "apua": TranslationKey.HELP_INTRO,
    "yleinen": TranslationKey.HELP_INTRO,
    "general": TranslationKey.HELP_INTRO,
    "komennot": TranslationKey.HELP_COMMANDS,
    "commands": TranslationKey.HELP_COMMANDS,
    "visualisointi": TranslationKey.HELP_VISUALIZATION,
    "visualisoinnit": TranslationKey.HELP_VISUALIZATION,
    "visualization": TranslationKey.HELP_VISUALIZATION,
    "visualizations": TranslationKey.HELP_VISUALIZATION,
    "kuvaajat": TranslationKey.HELP_VISUALIZATION,
    "somekuva": TranslationKey.HELP_SOCIAL_IMAGE,
    "social": TranslationKey.HELP_SOCIAL_IMAGE,
    "social_image": TranslationKey.HELP_SOCIAL_IMAGE,
    "share_image": TranslationKey.HELP_SOCIAL_IMAGE,
    "privacy": TranslationKey.HELP_PRIVACY,
    "tietosuoja": TranslationKey.HELP_PRIVACY,
}


class HelpWorkflow:
    def handle(self, event: CanonicalEvent, route: RouteDecision) -> WorkflowResult:
        ephemeral = event.metadata.get("command_name") is not None
        return build_help_result(ephemeral=ephemeral, topic=_topic_from_event(event))


def build_help_result(*, ephemeral: bool = True, topic: str = "") -> WorkflowResult:
    kind = OutgoingKind.EPHEMERAL_TEXT if ephemeral else OutgoingKind.TEXT
    key = HELP_TOPIC_KEYS.get(_normalize_topic(topic), TranslationKey.HELP_UNKNOWN_TOPIC)
    messages = (
        OutgoingMessage(
            kind=kind,
            localized_text=LocalizedText(key=key),
        ),
    )
    return WorkflowResult(status=WorkflowStatus.SUCCESS, messages=messages)


def _topic_from_event(event: CanonicalEvent) -> str:
    options = event.metadata.get("options", {})
    if isinstance(options, dict):
        topic = options.get("aihe") or options.get("topic") or ""
        if topic:
            return str(topic)
    return event.text


def _normalize_topic(value: str) -> str:
    text = value.strip().lower()
    if text.startswith("/help"):
        return text.removeprefix("/help").strip()
    return text
