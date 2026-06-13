from __future__ import annotations

from core.events import CanonicalEvent
from core.i18n import LocalizedText, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus


HELP_KEYS = (
    TranslationKey.HELP_INTRO,
    TranslationKey.HELP_UPLOAD_GPX,
    TranslationKey.HELP_WORKOUTS,
    TranslationKey.HELP_VISUALIZATION,
    TranslationKey.HELP_DEBUG,
)


class HelpWorkflow:
    def handle(self, event: CanonicalEvent, route: RouteDecision) -> WorkflowResult:
        ephemeral = event.metadata.get("command_name") is not None
        return build_help_result(ephemeral=ephemeral)


def build_help_result(*, ephemeral: bool = True) -> WorkflowResult:
    kind = OutgoingKind.EPHEMERAL_TEXT if ephemeral else OutgoingKind.TEXT
    messages = tuple(
        OutgoingMessage(
            kind=kind,
            localized_text=LocalizedText(key=key),
        )
        for key in HELP_KEYS
    )
    return WorkflowResult(status=WorkflowStatus.SUCCESS, messages=messages)

