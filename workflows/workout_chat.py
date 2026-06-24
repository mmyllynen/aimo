from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from core.events import CanonicalEvent
from core.errors import AppError, ErrorCategory
from core.i18n import LocalizedText, SupportedLanguage, TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from llm.gateway import LLMGateway, LLMGatewayError
from llm.operations import (
    PeriodAnalysisReplyInput,
    PeriodRequest,
    PeriodRequestInput,
    RouteTimeEstimateExplanationIntentInput,
    RouteTimeEstimateExplanationReplyInput,
    RouteTimeEstimateIntentInput,
    RouteTimeEstimateReplyInput,
    WorkoutReferenceInput,
    WorkoutReplyInput,
    extract_workout_reference,
    interpret_route_time_estimate_explanation_intent,
    interpret_route_time_estimate_intent,
    interpret_period_request,
    write_period_analysis_reply,
    write_route_time_estimate_explanation_reply,
    write_route_time_estimate_reply,
    write_workout_reply,
)
from storage.repositories import HistoryEventRecord, WorkoutPointRecord, WorkoutRecord, WorkoutStreamRecord
from storage.unit_of_work import RepositoryBundle
from workout.route_estimate import RouteTimeEstimate, estimate_route_time_from_features, format_route_time_estimate
from weather.adjustment import weather_adjustment
from weather.service import WeatherLocation, WeatherProvider, climatology_weather
from workout.periods import DEFAULT_PERIOD_TIMEZONE, PeriodRequestError, aggregate_period, local_now, resolve_period_bounds
from workout.references import WorkoutReferenceResolution, WorkoutReferenceStatus, resolve_workout_reference


@dataclass(frozen=True)
class ResolvedWorkoutChat:
    workout: WorkoutRecord | None
    selector_type: str
    status: WorkoutReferenceStatus = WorkoutReferenceStatus.MATCHED
    set_current_workout: bool = False


class WorkoutChatWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
        *,
        gateway: LLMGateway | None,
        language: SupportedLanguage,
        weather_provider: WeatherProvider | None = None,
    ) -> WorkflowResult:
        if _is_route_time_estimate_request(event, route):
            return _handle_route_time_estimate(event, route, repositories, gateway, language, weather_provider=weather_provider)
        if gateway is None:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Workout chat requires an LLM gateway",
            )

        try:
            period_request = _interpret_period_request(event, repositories, gateway)
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Workout period interpretation failed",
            )
        if period_request.is_period_request:
            return _handle_period_request(event, repositories, gateway, language, period_request)

        try:
            route_time_intent = interpret_route_time_estimate_intent(
                gateway,
                RouteTimeEstimateIntentInput(
                    user_text=event.text,
                    current_date=local_now(event.created_at).date().isoformat(),
                    timezone=DEFAULT_PERIOD_TIMEZONE,
                    compact_routing_context={
                        "active_workout_id": _active_workout_id(repositories, event.user_id),
                        "recent_workout_count": len(repositories.workouts.list_for_user(event.user_id, limit=20)),
                    },
                ),
            )
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Route time estimate intent interpretation failed",
            )
        if route_time_intent.is_route_time_estimate:
            return _handle_route_time_estimate(
                event,
                route,
                repositories,
                gateway,
                language,
                conversational=True,
                weather_provider=weather_provider,
                activity_intent=route_time_intent.activity_intent,
                target_date=route_time_intent.target_date,
            )

        try:
            explanation_intent = interpret_route_time_estimate_explanation_intent(
                gateway,
                RouteTimeEstimateExplanationIntentInput(
                    user_text=event.text,
                    compact_routing_context={
                        "has_recent_route_time_estimate": _latest_route_time_estimate_event(repositories, event.channel_id) is not None,
                    },
                ),
            )
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Route time estimate explanation intent interpretation failed",
            )
        if explanation_intent.is_explanation_request:
            return _handle_route_time_estimate_explanation(event, repositories, gateway, language)

        try:
            resolved = _resolve_workout(event, repositories, gateway)
        except LLMGatewayError:
            return _error_result(
                WorkflowStatus.SYSTEM_ERROR,
                ErrorCategory.MODEL_UNAVAILABLE,
                TranslationKey.ERROR_MODEL_UNAVAILABLE,
                "Workout reference extraction failed",
            )
        if resolved.status == WorkoutReferenceStatus.AMBIGUOUS:
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.AMBIGUOUS_WORKOUT,
                TranslationKey.ERROR_AMBIGUOUS_WORKOUT,
                "Ambiguous workout reference for workout chat",
            )
        if resolved.workout is None and resolved.selector_type != "general":
            return _error_result(
                WorkflowStatus.USER_ERROR,
                ErrorCategory.NO_MATCHING_WORKOUT,
                TranslationKey.ERROR_NO_MATCHING_WORKOUT,
                "No matching workout for workout chat",
            )
        if resolved.workout is not None and resolved.set_current_workout:
            repositories.active_workouts.set(
                user_id=event.user_id,
                workout_id=resolved.workout.workout_id,
                updated_at=event.created_at,
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


def _handle_route_time_estimate(
    event: CanonicalEvent,
    route: RouteDecision,
    repositories: RepositoryBundle,
    gateway: LLMGateway | None,
    language: SupportedLanguage,
    conversational: bool = False,
    weather_provider: WeatherProvider | None = None,
    activity_intent: str = "unknown",
    target_date: str = "",
) -> WorkflowResult:
    try:
        resolved = _resolve_workout(event, repositories, gateway) if gateway is not None else _resolve_default_workout(event, repositories)
    except LLMGatewayError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.MODEL_UNAVAILABLE,
            TranslationKey.ERROR_MODEL_UNAVAILABLE,
            "Workout reference extraction failed for route time estimate",
        )
    if resolved.status == WorkoutReferenceStatus.AMBIGUOUS:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.AMBIGUOUS_WORKOUT,
            TranslationKey.ERROR_AMBIGUOUS_WORKOUT,
            "Ambiguous workout reference for route time estimate",
        )
    if resolved.workout is None:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.NO_MATCHING_WORKOUT,
            TranslationKey.ERROR_NO_MATCHING_WORKOUT,
            "No matching workout for route time estimate",
        )
    target_points = repositories.workout_streams.list_points(resolved.workout.workout_id)
    history = repositories.workouts.list_for_user(event.user_id, limit=100)
    target_feature = repositories.workout_estimate_features.get(resolved.workout.workout_id)
    history_features = repositories.workout_estimate_features.list_for_user(event.user_id, limit=100)
    estimate = estimate_route_time_from_features(resolved.workout, target_feature, target_points, history_features, history)
    if estimate is None:
        return WorkflowResult(
            status=WorkflowStatus.USER_ERROR,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.TEXT,
                    text="Reitti-aikaennuste tarvitsee reitin matkan.",
                ),
            ),
            error=AppError(
                category=ErrorCategory.MISSING_METRIC,
                message="Route time estimate requires route distance",
                user_message="Reitti-aikaennuste tarvitsee reitin matkan.",
            ),
        )
    weather_payload = _weather_payload(
        estimate,
        target_feature,
        target_points,
        target_date=target_date,
        activity_intent=activity_intent,
        provider=weather_provider,
    )
    reply_text = format_route_time_estimate(estimate, language=language.value)
    claims_used: tuple[str, ...] = ()
    missing_data_notes: tuple[str, ...] = estimate.missing_data
    if conversational and gateway is not None:
        try:
            reply = write_route_time_estimate_reply(
                gateway,
                RouteTimeEstimateReplyInput(
                    user_text=event.text,
                    estimate_facts=_route_time_estimate_facts(resolved.workout, estimate, weather_payload=weather_payload),
                    bounded_recent_context=_recent_context(repositories, event.channel_id),
                ),
                language=language,
            )
        except LLMGatewayError:
            reply_text = _format_route_time_estimate_fallback(estimate, weather_payload, language=language.value)
            missing_data_notes = (*estimate.missing_data, "route_time_reply_llm_unavailable")
        else:
            reply_text = reply.reply_text
            claims_used = reply.claims_used
            missing_data_notes = reply.missing_data_notes
    repositories.history.add(
        HistoryEventRecord(
            history_id=f"{event.event_id}:assistant",
            guild_id=event.guild_id,
            channel_id=event.channel_id,
            user_id=None,
            role="assistant",
            event_type="route_time_estimate",
            content=reply_text,
            source_event_id=event.event_id,
            created_at=event.created_at.isoformat(),
            metadata={
                "workout_id": resolved.workout.workout_id,
                "estimate_s": round(estimate.estimate_s),
                "low_s": round(estimate.low_s),
                "high_s": round(estimate.high_s),
                "confidence": estimate.confidence,
                "comparable_count": estimate.comparable_count,
                "model": estimate.model,
                "similarity": estimate.similarity or {},
                "explanation": estimate.explanation or {},
                "weather": weather_payload or {},
                "conversational": conversational,
                "claims_used": list(claims_used),
                "missing_data_notes": list(missing_data_notes),
            },
        )
    )
    return WorkflowResult(
        status=WorkflowStatus.SUCCESS,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.TEXT,
                text=reply_text,
                metadata={
                    "workout_id": resolved.workout.workout_id,
                    "route_time_estimate_s": round(estimate.estimate_s),
                    "route_time_low_s": round(estimate.low_s),
                    "route_time_high_s": round(estimate.high_s),
                    "route_time_confidence": estimate.confidence,
                    "route_time_comparable_count": estimate.comparable_count,
                    "route_time_model": estimate.model,
                    "route_time_similarity": estimate.similarity or {},
                    "route_time_explanation": estimate.explanation or {},
                    "route_time_weather": weather_payload or {},
                    "route_time_missing_data": estimate.missing_data,
                    "route_time_estimate_requested": bool(route.slots.get("route_time_estimate")),
                    "route_time_conversational": conversational,
                    "claims_used": claims_used,
                    "missing_data_notes": missing_data_notes,
                },
            ),
        ),
    )


def _handle_route_time_estimate_explanation(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    gateway: LLMGateway,
    language: SupportedLanguage,
) -> WorkflowResult:
    latest = _latest_route_time_estimate_event(repositories, event.channel_id)
    if latest is None:
        return WorkflowResult(
            status=WorkflowStatus.USER_ERROR,
            messages=(
                OutgoingMessage(
                    kind=OutgoingKind.TEXT,
                    text="En löydä aiempaa reitti-aikaennustetta tästä kanavasta.",
                ),
            ),
            error=AppError(
                category=ErrorCategory.NO_MATCHING_WORKOUT,
                message="No previous route time estimate to explain",
                user_message="En löydä aiempaa reitti-aikaennustetta tästä kanavasta.",
            ),
        )
    facts = _route_time_explanation_facts(latest)
    try:
        reply = write_route_time_estimate_explanation_reply(
            gateway,
            RouteTimeEstimateExplanationReplyInput(
                user_text=event.text,
                explanation_facts=facts,
                bounded_recent_context=_recent_context(repositories, event.channel_id),
            ),
            language=language,
        )
    except LLMGatewayError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.MODEL_UNAVAILABLE,
            TranslationKey.ERROR_MODEL_UNAVAILABLE,
            "Route time estimate explanation reply generation failed",
        )
    repositories.history.add(
        HistoryEventRecord(
            history_id=f"{event.event_id}:assistant",
            guild_id=event.guild_id,
            channel_id=event.channel_id,
            user_id=None,
            role="assistant",
            event_type="route_time_estimate_explanation",
            content=reply.reply_text,
            source_event_id=event.event_id,
            created_at=event.created_at.isoformat(),
            metadata={
                "explained_history_id": latest.history_id,
                "claims_used": list(reply.claims_used),
                "missing_data_notes": list(reply.missing_data_notes),
                "explanation_facts": facts,
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
                    "explained_history_id": latest.history_id,
                    "route_time_explanation_requested": True,
                    "claims_used": reply.claims_used,
                    "missing_data_notes": reply.missing_data_notes,
                },
            ),
        ),
    )


def _is_route_time_estimate_request(event: CanonicalEvent, route: RouteDecision) -> bool:
    if route.slots.get("route_time_estimate") is True:
        return True
    text = event.text.lower().replace("-", "_")
    return any(token in {"+estimate", "+ennuste", "+aikaennuste", "+time_estimate"} for token in text.split())


def _resolve_default_workout(event: CanonicalEvent, repositories: RepositoryBundle) -> ResolvedWorkoutChat:
    resolved = resolve_workout_reference(repositories, event.user_id, "active", default="active")
    if resolved.status == WorkoutReferenceStatus.MATCHED:
        return _from_reference(resolved)
    return _from_reference(resolve_workout_reference(repositories, event.user_id, "latest", default="latest"))


def _latest_route_time_estimate_event(repositories: RepositoryBundle, channel_id: str) -> HistoryEventRecord | None:
    for record in reversed(repositories.history.list_recent_for_channel(channel_id, limit=50)):
        if record.event_type == "route_time_estimate":
            return record
    return None


def _route_time_explanation_facts(record: HistoryEventRecord) -> dict[str, object]:
    metadata = record.metadata
    explanation = metadata.get("explanation", {}) if isinstance(metadata.get("explanation", {}), dict) else {}
    similarity = metadata.get("similarity", {}) if isinstance(metadata.get("similarity", {}), dict) else {}
    weather = metadata.get("weather", {}) if isinstance(metadata.get("weather", {}), dict) else {}
    return {
        "history_id": record.history_id,
        "workout_id": str(metadata.get("workout_id", "")),
        "estimate_s": metadata.get("estimate_s"),
        "estimate_text": _format_duration(float(metadata.get("estimate_s", 0) or 0)),
        "low_s": metadata.get("low_s"),
        "low_text": _format_duration(float(metadata.get("low_s", 0) or 0)),
        "high_s": metadata.get("high_s"),
        "high_text": _format_duration(float(metadata.get("high_s", 0) or 0)),
        "confidence": str(metadata.get("confidence", "")),
        "comparable_count": int(metadata.get("comparable_count", 0) or 0),
        "model": str(metadata.get("model", "")),
        "baseline_pace_s_per_km": explanation.get("baseline_pace_s_per_km"),
        "baseline_pace_text": explanation.get("baseline_pace_text", ""),
        "ascent_penalty_s": explanation.get("ascent_penalty_s"),
        "ascent_penalty_text": explanation.get("ascent_penalty_text", ""),
        "distance_adjustment_s": explanation.get("distance_adjustment_s"),
        "distance_adjustment_text": explanation.get("distance_adjustment_text", ""),
        "uncertainty_source": explanation.get("uncertainty_source", ""),
        "effective_sample_size": explanation.get("effective_sample_size", similarity.get("effective_sample_size")),
        "similarity": {
            "candidate_count": similarity.get("candidate_count"),
            "effective_sample_size": similarity.get("effective_sample_size"),
            "target_distance_band": similarity.get("target_distance_band", ""),
            "target_ascent_band": similarity.get("target_ascent_band", ""),
            "top_weights": list(similarity.get("top_weights", ()))[:5] if isinstance(similarity.get("top_weights", ()), list) else [],
            "top_distance_scores": list(similarity.get("top_distance_scores", ()))[:5]
            if isinstance(similarity.get("top_distance_scores", ()), list)
            else [],
            "top_ascent_scores": list(similarity.get("top_ascent_scores", ()))[:5]
            if isinstance(similarity.get("top_ascent_scores", ()), list)
            else [],
            "top_grade_scores": list(similarity.get("top_grade_scores", ()))[:5]
            if isinstance(similarity.get("top_grade_scores", ()), list)
            else [],
        },
        "missing_data_notes": list(metadata.get("missing_data_notes", ())) if isinstance(metadata.get("missing_data_notes", ()), list) else [],
        "weather": weather,
    }


def _weather_payload(
    estimate: RouteTimeEstimate,
    target_feature,
    target_points: tuple[WorkoutPointRecord, ...],
    *,
    target_date: str,
    activity_intent: str,
    provider: WeatherProvider | None,
) -> dict[str, object] | None:
    if not target_date:
        return None
    try:
        parsed_date = date.fromisoformat(target_date)
    except ValueError:
        return {
            "requested": True,
            "available": False,
            "target_date": target_date,
            "limitations": ["invalid_target_date"],
        }
    location = _weather_location(target_feature, target_points)
    if location is None:
        return {
            "requested": True,
            "available": False,
            "target_date": target_date,
            "limitations": ["missing_route_location"],
        }
    weather = provider.get_weather(location, parsed_date) if provider is not None else climatology_weather(location, parsed_date, limitations=("weather_provider_unavailable",))
    adjustment = weather_adjustment(estimate.estimate_s, weather, activity=activity_intent)
    adjusted = max(60.0, estimate.estimate_s + adjustment.adjustment_s)
    return {
        "requested": True,
        "available": True,
        "activity_intent": activity_intent or "unknown",
        "target_date": parsed_date.isoformat(),
        "base_estimate_s": round(estimate.estimate_s),
        "adjusted_estimate_s": round(adjusted),
        "adjusted_estimate_text": _format_duration(adjusted),
        "adjustment_s": round(adjustment.adjustment_s),
        "adjustment_text": _format_signed_duration(adjustment.adjustment_s),
        "multiplier": round(adjustment.multiplier, 4),
        "source": adjustment.facts.get("source", ""),
        "facts": adjustment.facts,
        "components": {key: round(value) for key, value in adjustment.components.items()},
        "limitations": list(adjustment.limitations),
    }


def _weather_location(target_feature, target_points: tuple[WorkoutPointRecord, ...]) -> WeatherLocation | None:
    if target_feature is not None:
        location = target_feature.metadata.get("location", {}) if isinstance(target_feature.metadata, dict) else {}
        lat = location.get("centroid_latitude")
        lon = location.get("centroid_longitude")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            return WeatherLocation(latitude=float(lat), longitude=float(lon), label="route_centroid")
    coordinates = tuple(
        (point.latitude, point.longitude)
        for point in target_points
        if point.latitude is not None and point.longitude is not None
    )
    if not coordinates:
        return None
    return WeatherLocation(
        latitude=sum(float(lat) for lat, _ in coordinates) / len(coordinates),
        longitude=sum(float(lon) for _, lon in coordinates) / len(coordinates),
        label="route_centroid_from_points",
    )


def _route_time_estimate_facts(
    workout: WorkoutRecord,
    estimate: RouteTimeEstimate,
    *,
    weather_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    facts = {
        "workout_id": workout.workout_id,
        "title": workout.title,
        "kind": workout.kind,
        "primary_kind": workout.primary_kind,
        "local_date": workout.local_date,
        "estimate_s": round(estimate.estimate_s),
        "estimate_text": _format_duration(estimate.estimate_s),
        "low_s": round(estimate.low_s),
        "low_text": _format_duration(estimate.low_s),
        "high_s": round(estimate.high_s),
        "high_text": _format_duration(estimate.high_s),
        "route_distance_km": estimate.route_distance_km,
        "route_ascent_m": estimate.route_ascent_m,
        "baseline_pace_s_per_km": estimate.baseline_pace_s_per_km,
        "ascent_penalty_s": round(estimate.ascent_penalty_s),
        "distance_adjustment_s": round(estimate.distance_adjustment_s),
        "confidence": estimate.confidence,
        "comparable_workout_count": estimate.comparable_count,
        "model": estimate.model,
        "similarity": estimate.similarity or {},
        "explanation": estimate.explanation or {},
        "missing_data": list(estimate.missing_data),
    }
    if weather_payload is not None:
        facts["weather"] = weather_payload
    return facts


def _format_duration(seconds: float) -> str:
    total_minutes = max(1, int(round(seconds / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}"
    return f"{minutes} min"


def _format_route_time_estimate_fallback(
    estimate: RouteTimeEstimate,
    weather_payload: dict[str, object] | None,
    *,
    language: str,
) -> str:
    text = format_route_time_estimate(estimate, language=language)
    if not weather_payload or not weather_payload.get("available"):
        return text
    adjusted = str(weather_payload.get("adjusted_estimate_text", ""))
    adjustment = str(weather_payload.get("adjustment_text", ""))
    source = str(weather_payload.get("source", ""))
    target_date = str(weather_payload.get("target_date", ""))
    limitations = weather_payload.get("limitations", [])
    limitation_text = ""
    if isinstance(limitations, list) and limitations:
        limitation_text = f" Rajoitteet: {', '.join(str(item) for item in limitations)}."
    if language == "en":
        return "\n".join(
            (
                text,
                "",
                f"Weather-adjusted estimate for {target_date}: {adjusted} ({adjustment}, source: {source}).{limitation_text}",
            )
        )
    return "\n".join(
        (
            text,
            "",
            f"Sääkorjattu arvio päivälle {target_date}: {adjusted} ({adjustment}, lähde: {source}).{limitation_text}",
        )
    )


def _format_signed_duration(seconds: float) -> str:
    if abs(seconds) < 30:
        return "+0 min"
    sign = "+" if seconds >= 0 else "-"
    return f"{sign}{_format_duration(abs(seconds))}"


def _interpret_period_request(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    gateway: LLMGateway,
) -> PeriodRequest:
    current = local_now(event.created_at)
    return interpret_period_request(
        gateway,
        PeriodRequestInput(
            user_text=event.text,
            current_datetime=current.isoformat(),
            timezone=DEFAULT_PERIOD_TIMEZONE,
            compact_routing_context={
                "recent_workout_count": len(repositories.workouts.list_for_user(event.user_id, limit=20)),
                "active_workout_id": _active_workout_id(repositories, event.user_id),
            },
        ),
    )


def _handle_period_request(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    gateway: LLMGateway,
    language: SupportedLanguage,
    period_request: PeriodRequest,
) -> WorkflowResult:
    try:
        bounds = resolve_period_bounds(period_request, local_now(event.created_at))
    except PeriodRequestError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.PERIOD_REQUEST_INVALID,
            TranslationKey.ERROR_PERIOD_REQUEST_INVALID,
            "Invalid workout period request",
        )
    filters = period_request.filters
    workouts = repositories.workouts.list_for_user_in_period(
        event.user_id,
        start_date=bounds.start_date,
        end_date=bounds.end_date,
        kind=str(filters.get("kind", "") or "") or None,
        primary_kind=str(filters.get("primary_kind", "") or "") or None,
    )
    if not workouts:
        return _error_result(
            WorkflowStatus.USER_ERROR,
            ErrorCategory.NO_WORKOUTS_IN_PERIOD,
            TranslationKey.ERROR_NO_WORKOUTS_IN_PERIOD,
            "No workouts found for workout period request",
        )
    try:
        facts = aggregate_period(workouts, period_request, bounds)
    except PeriodRequestError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.PERIOD_REQUEST_INVALID,
            TranslationKey.ERROR_PERIOD_REQUEST_INVALID,
            "Invalid workout period aggregation request",
        )
    try:
        reply = write_period_analysis_reply(
            gateway,
            PeriodAnalysisReplyInput(
                user_text=event.text,
                period_facts=facts,
                bounded_recent_context=_recent_context(repositories, event.channel_id),
            ),
            language=language,
        )
    except LLMGatewayError:
        return _error_result(
            WorkflowStatus.SYSTEM_ERROR,
            ErrorCategory.MODEL_UNAVAILABLE,
            TranslationKey.ERROR_MODEL_UNAVAILABLE,
            "Workout period reply generation failed",
        )

    repositories.history.add(
        HistoryEventRecord(
            history_id=f"{event.event_id}:assistant",
            guild_id=event.guild_id,
            channel_id=event.channel_id,
            user_id=None,
            role="assistant",
            event_type="workout_period_reply",
            content=reply.reply_text,
            source_event_id=event.event_id,
            created_at=event.created_at.isoformat(),
            metadata={
                "claims_used": list(reply.claims_used),
                "missing_data_notes": list(reply.missing_data_notes),
                "period_scope_type": period_request.scope_type,
                "period_start_date": bounds.start_date or "",
                "period_end_date": bounds.end_date or "",
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
                    "claims_used": reply.claims_used,
                    "missing_data_notes": reply.missing_data_notes,
                    "period_scope_type": period_request.scope_type,
                    "period_start_date": bounds.start_date or "",
                    "period_end_date": bounds.end_date or "",
                    "workout_count": facts["workout_count"],
                },
            ),
        ),
    )


def _active_workout_id(repositories: RepositoryBundle, user_id: str) -> str:
    active = repositories.active_workouts.get(user_id)
    return active.workout_id if active is not None else ""


def _resolve_workout(
    event: CanonicalEvent,
    repositories: RepositoryBundle,
    gateway: LLMGateway,
) -> ResolvedWorkoutChat:
    candidates = repositories.workouts.list_for_user(event.user_id, limit=20)
    active = repositories.active_workouts.get(event.user_id)
    reference = extract_workout_reference(
        gateway,
        WorkoutReferenceInput(
            user_text=event.text,
            candidate_workouts=tuple(_candidate_fact(workout) for workout in candidates),
            active_workout=_candidate_fact(active) if active is not None else None,
        ),
    )
    if reference.selector_type in {"general", "none", ""} and not reference.matched_workout_ids:
        return ResolvedWorkoutChat(workout=None, selector_type="general")
    if len(reference.matched_workout_ids) > 1 or reference.requires_clarification:
        return ResolvedWorkoutChat(
            workout=None,
            selector_type=reference.selector_type,
            status=WorkoutReferenceStatus.AMBIGUOUS,
        )
    if len(reference.matched_workout_ids) == 1:
        return _from_reference(
            resolve_workout_reference(
                repositories,
                event.user_id,
                reference.matched_workout_ids[0],
                default="none",
            ),
            set_current_workout=reference.set_current_workout,
        )
    return _from_reference(
        resolve_workout_reference(
            repositories,
            event.user_id,
            reference.selector_value,
            default=reference.selector_type if reference.selector_type in {"latest", "active"} else "none",
        ),
        set_current_workout=reference.set_current_workout,
    )


def _from_reference(resolved: WorkoutReferenceResolution, *, set_current_workout: bool = False) -> ResolvedWorkoutChat:
    return ResolvedWorkoutChat(
        workout=resolved.workout,
        selector_type=resolved.selector_type,
        status=resolved.status,
        set_current_workout=set_current_workout and resolved.status == WorkoutReferenceStatus.MATCHED,
    )


def _candidate_fact(workout: WorkoutRecord) -> dict[str, object]:
    return {
        "workout_id": workout.workout_id,
        "title": workout.title,
        "kind": workout.kind,
        "primary_kind": workout.primary_kind,
        "local_date": workout.local_date,
        "start_time_local": workout.start_time_local,
        "distance_km": workout.distance_km,
        "duration_s": workout.duration_s,
    }


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
