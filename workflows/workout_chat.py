from __future__ import annotations

from dataclasses import dataclass

from core.events import CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import WorkoutReplyInput, write_workout_reply
from storage.repositories import HistoryEventRecord, WorkoutRecord, WorkoutStreamRecord
from storage.unit_of_work import RepositoryBundle


@dataclass(frozen=True)
class ResolvedWorkoutChat:
    workout: WorkoutRecord | None
    selector_type: str


class WorkoutChatWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        gateway: LLMGateway | None,
        language: SupportedLanguage,
    ) -> WorkflowResult:
        if gateway is None:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Workout chat requires an LLM gateway",
            )

        resolved = _resolve_workout(event, repositories)
        if resolved.workout is None and resolved.selector_type in {"latest", "active", "id"}:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.NO_MATCHING_WORKOUT,
                TranslationKey.ERROR_NO_MATCHING_WORKOUT,
                "No matching workout for workout chat",
            )

        facts = _workout_facts(resolved.workout, repositories) if resolved.workout is not None else None
        missing = _missing_summary_facts(resolved.workout) if resolved.workout is not None else ()
        try:
            reply = write_workout_reply(
                gateway,
                WorkoutReplyInput(
                    user_text=event.text,
                    resolved_workout_facts=facts,
                    missing_data_facts=missing,
                    profile_facts={"selector_type": resolved.selector_type},
                    bounded_recent_context=_recent_context(repositories, event.channel_id),
                ),
                language=language,
            )
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Workout reply generation failed",
            )

        repositories.history.add(
            HistoryEventRecord(
                history_id=f"{event.event_id}:assistant",
                guild_id=event.guild_id,
                channel_id=event.channel_id,
                user_id=None,
                role="assistant",
                event_type="workout_reply",
                content=reply.reply_text,
                source_event_id=event.event_id,
                created_at=event.created_at.isoformat(),
                metadata={
                    "claims_used": list(reply.claims_used),
                    "missing_data_notes": list(reply.missing_data_notes),
                    "workout_id": resolved.workout.workout_id if resolved.workout else "",
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
                        "workout_id": resolved.workout.workout_id if resolved.workout else "",
                        "claims_used": reply.claims_used,
                        "missing_data_notes": reply.missing_data_notes,
                    },
                ),
            ),
        )


def _resolve_workout(event: CanonicalEvent, repositories: RepositoryBundle) -> ResolvedWorkoutChat:
    text = event.text.lower()
    if "aktiiv" in text or "active" in text:
        return ResolvedWorkoutChat(workout=repositories.active_workouts.get(event.user_id), selector_type="active")
    workout_id = _explicit_workout_id(event.text)
    if workout_id:
        return ResolvedWorkoutChat(
            workout=repositories.workouts.get_for_user(event.user_id, workout_id),
            selector_type="id",
        )
    if "viime" in text or "latest" in text or "last" in text or "treeni" in text or "workout" in text:
        return ResolvedWorkoutChat(workout=repositories.workouts.latest_for_user(event.user_id), selector_type="latest")
    return ResolvedWorkoutChat(workout=None, selector_type="general")


def _explicit_workout_id(text: str) -> str:
    for part in text.replace(",", " ").replace(".", " ").split():
        if part.startswith("workout-"):
            return part
    return ""


def _workout_facts(workout: WorkoutRecord, repositories: RepositoryBundle) -> dict[str, object]:
    streams = repositories.workout_streams.list_streams(workout.workout_id)
    return {
        "workout_id": workout.workout_id,
        "title": workout.title,
        "kind": workout.kind,
        "primary_kind": workout.primary_kind,
        "local_date": workout.local_date,
        "distance_km": workout.distance_km,
        "duration_s": workout.duration_s,
        "pace_s_per_km": workout.pace_s_per_km,
        "ascent_m": workout.ascent_m,
        "avg_hr_bpm": workout.avg_hr_bpm,
        "max_hr_bpm": workout.max_hr_bpm,
        "point_count": workout.point_count,
        "stream_manifest": [_stream_fact(stream) for stream in streams],
    }


def _stream_fact(stream: WorkoutStreamRecord) -> dict[str, object]:
    return {
        "stream_key": stream.stream_key,
        "unit": stream.unit,
        "sample_count": stream.sample_count,
        "min_value": stream.min_value,
        "max_value": stream.max_value,
        "avg_value": stream.avg_value,
    }


def _missing_summary_facts(workout: WorkoutRecord | None) -> tuple[str, ...]:
    if workout is None:
        return ()
    missing = []
    for key in ("distance_km", "duration_s", "pace_s_per_km", "avg_hr_bpm", "max_hr_bpm"):
        if getattr(workout, key) is None:
            missing.append(key)
    return tuple(missing)


def _recent_context(repositories: RepositoryBundle, channel_id: str) -> tuple[dict[str, str], ...]:
    records = repositories.history.list_recent_for_channel(channel_id, limit=8)
    return tuple(
        {
            "role": record.role,
            "event_type": record.event_type,
            "content": record.content[:500],
            "created_at": record.created_at,
        }
        for record in records
        if record.content
    )


def _error_result(
    status: WorkflowStatus,
    category: ErrorCategory,
    message_key: TranslationKey,
    message: str,
) -> WorkflowResult:
    return WorkflowResult(
        status=status,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                localized_text=LocalizedText(key=message_key),
            ),
        ),
        error=AppError(category=category, message=message, user_message_key=message_key.value),
    )
