from __future__ import annotations

from dataclasses import dataclass

from core.events import CanonicalEvent, EventKind
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import ChatReplyInput, write_chat_reply
from storage.repositories import HistoryEventRecord
from storage.unit_of_work import RepositoryBundle


MAX_CONTEXT_EVENTS = 12
MAX_CONTEXT_CONTENT_CHARS = 500


@dataclass(frozen=True)
class ChatWorkflowConfig:
    context_event_limit: int = MAX_CONTEXT_EVENTS
    context_content_chars: int = MAX_CONTEXT_CONTENT_CHARS


class ChatWorkflow:
    def __init__(self, config: ChatWorkflowConfig | None = None) -> None:
        self.config = config or ChatWorkflowConfig()

    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        gateway: LLMGateway | None,
        language: SupportedLanguage,
    ) -> WorkflowResult:
        if event.kind == EventKind.MESSAGE:
            return WorkflowResult(status=WorkflowStatus.NOOP)
        if gateway is None:
            return _model_unavailable_result()

        try:
            reply = write_chat_reply(
                gateway,
                ChatReplyInput(
                    user_text=event.text,
                    bounded_recent_context=_recent_context(
                        repositories,
                        event.channel_id,
                        limit=self.config.context_event_limit,
                        content_chars=self.config.context_content_chars,
                    ),
                    workflow_facts={
                        "route_confidence": route.confidence.value,
                        "route_reason": route.reason,
                    },
                ),
                language=language,
            )
        except LLMGatewayError:
            return _model_unavailable_result()

        repositories.history.add(
            HistoryEventRecord(
                history_id=f"{event.event_id}:assistant",
                guild_id=event.guild_id,
                channel_id=event.channel_id,
                user_id=None,
                role="assistant",
                event_type="chat_reply",
                content=reply.reply_text,
                source_event_id=event.event_id,
                created_at=event.created_at.isoformat(),
                metadata={
                    "tone": reply.tone,
                    "should_update_summary": reply.should_update_summary,
                },
            )
        )

        return WorkflowResult(
            status=WorkflowStatus.SUCCESS,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.TEXT,
                    text=reply.reply_text,
                    metadata={
                        "tone": reply.tone,
                        "should_update_summary": reply.should_update_summary,
                    },
                ),
            ),
        )


def _recent_context(
    repositories: RepositoryBundle,
    channel_id: str,
    *,
    limit: int,
    content_chars: int,
) -> tuple[dict[str, str], ...]:
    records = repositories.history.list_recent_for_channel(channel_id, limit=limit)
    return tuple(
        {
            "role": record.role,
            "event_type": record.event_type,
            "content": _truncate(record.content, content_chars),
            "created_at": record.created_at,
        }
        for record in records
        if record.content
    )


def _truncate(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return value[:max_chars]


def _model_unavailable_result() -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.SYSTEM_ERROR,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=TranslationKey.ERROR_MODEL_UNAVAILABLE),
            ),
        ),
    )
