from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.i18n import SupportedLanguage
from core.routing import RouteConfidence, RouteDecision, WorkflowTarget
from llm.gateway import LLMGateway, LLMOperation, LLMRequest


JsonObject = dict[str, Any]
VISUALIZATION_SELECTOR_TYPES = (
    "latest",
    "active",
    "id",
    "date",
    "text",
    "list_index",
    "all_workouts",
    "current_week",
    "last_week",
    "current_month",
    "last_month",
    "rolling_days",
    "date_range",
    "calendar_year_to_date",
)
VISUALIZATION_METRICS = (
    "elapsed_s",
    "distance_km",
    "latitude",
    "longitude",
    "elevation_m",
    "heart_rate_bpm",
    "cadence_spm",
    "pace_s_per_km",
    "heart_rate_zone_seconds",
    "route",
    "duration_s",
    "ascent_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "point_count",
    "local_date",
)
VISUALIZATION_TRANSFORMS = (
    "normalize_to_primary_range",
    "rolling_average",
    "aggregate_sum",
    "aggregate_avg",
    "as_percentage_of_total",
)
VISUALIZATION_LAYOUT_MODES = ("auto", "single_axis", "small_multiples")
VISUALIZATION_CHART_KINDS = ("auto", "line", "bar", "pie", "map")
VISUALIZATION_OUTPUT_MODES = ("chart", "social_image")
PERIOD_SCOPE_TYPES = (
    "none",
    "single_workout",
    "all_workouts",
    "current_week",
    "last_week",
    "current_month",
    "last_month",
    "rolling_days",
    "date_range",
    "calendar_year_to_date",
)
PERIOD_GROUPINGS = ("none", "day", "week", "month")
PERIOD_OUTPUT_MODES = ("prose", "visualization", "both")
PERIOD_COMPARISON_MODES = ("none", "previous_period")
PERIOD_METRICS = (
    "workout_count",
    "distance_km",
    "duration_s",
    "ascent_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "point_count",
)


@dataclass(frozen=True)
class IntentClassificationInput:
    event_kind: str
    user_text: str
    has_attachments: bool
    compact_channel_state: JsonObject = field(default_factory=dict)
    recent_summary: str = ""


@dataclass(frozen=True)
class WorkoutReferenceInput:
    user_text: str
    candidate_workouts: tuple[JsonObject, ...] = ()
    active_workout: JsonObject | None = None


@dataclass(frozen=True)
class WorkoutReference:
    selector_type: str
    selector_value: str
    matched_workout_ids: tuple[str, ...]
    ambiguity_reason: str
    requires_clarification: bool
    set_current_workout: bool = False


@dataclass(frozen=True)
class PeriodRequestInput:
    user_text: str
    current_datetime: str
    timezone: str
    compact_routing_context: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class PeriodRequest:
    scope_type: str
    scope_value: str
    start_date: str
    end_date: str
    rolling_days: int | None
    filters: JsonObject
    metrics: tuple[str, ...]
    grouping: str
    output_mode: str
    comparison_mode: str
    reason: str = ""

    @property
    def is_period_request(self) -> bool:
        return self.scope_type not in {"none", "single_workout"}


@dataclass(frozen=True)
class PeriodAnalysisReplyInput:
    user_text: str
    period_facts: JsonObject
    bounded_recent_context: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class PeriodAnalysisReply:
    reply_text: str
    claims_used: tuple[str, ...]
    missing_data_notes: tuple[str, ...]


@dataclass(frozen=True)
class ChatReplyInput:
    user_text: str
    bounded_recent_context: tuple[JsonObject, ...] = ()
    channel_summary: str = ""
    profile_facts: JsonObject = field(default_factory=dict)
    workflow_facts: JsonObject = field(default_factory=dict)


@dataclass(frozen=True)
class ChatReply:
    reply_text: str
    tone: str
    should_update_summary: bool


@dataclass(frozen=True)
class WorkoutReplyInput:
    user_text: str
    resolved_workout_facts: JsonObject | None = None
    missing_data_facts: tuple[str, ...] = ()
    profile_facts: JsonObject = field(default_factory=dict)
    bounded_recent_context: tuple[JsonObject, ...] = ()


@dataclass(frozen=True)
class WorkoutReply:
    reply_text: str
    claims_used: tuple[str, ...]
    missing_data_notes: tuple[str, ...]


@dataclass(frozen=True)
class VisualizationIntentInput:
    user_text: str
    compact_routing_context: JsonObject = field(default_factory=dict)
    previous_visualization: JsonObject | None = None


@dataclass(frozen=True)
class VisualizationIntentRevisionInput:
    user_text: str
    failed_intent: JsonObject
    validation_errors: tuple[JsonObject, ...]
    dataset_manifest: JsonObject
    allowed_primitives: JsonObject
    previous_visualization: JsonObject | None = None


@dataclass(frozen=True)
class VisualizationIntent:
    workout_selector: JsonObject
    x_metric: str
    y_metrics: tuple[str, ...]
    transforms: tuple[str, ...]
    date_range: JsonObject
    comparison_mode: str
    layout_mode: str = "auto"
    chart_kind: str = "auto"
    context_update: JsonObject = field(default_factory=dict)
    route_color_metric: str = ""
    route_color_ignored_metrics: tuple[str, ...] = ()
    render_width: int = 0
    render_height: int = 0
    output_mode: str = "chart"


def classify_intent(gateway: LLMGateway, data: IntentClassificationInput) -> RouteDecision:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.INTENT_CLASSIFICATION,
            system_prompt=(
                "Classify the Aimo workflow. Return only structured JSON. "
                "Use visualization for any request to draw, plot, render, chart, graph, visualize, compare in a chart, "
                "or change/refine a previous chart. Finnish examples include piirra/piirrä, kuvaaja, graafi, käyrä, "
                "piirakka, jakauma, sykealuejakauma, and 'sama kuvaaja'. "
                "Use workout_chat for coaching, analysis, or questions about workout facts without asking for an image/chart. "
                "Use workout_management only for deterministic slash-command style management. "
                "Use chat only for general conversation that does not belong to a specialized workflow. "
                "A public mention can access stored workouts through visualization and workout_chat workflows; do not route "
                "workout chart requests to chat."
            ),
            user_payload={
                "event_kind": data.event_kind,
                "user_text": data.user_text,
                "has_attachments": data.has_attachments,
                "workflow_catalog": _workflow_catalog(),
                "compact_channel_state": data.compact_channel_state,
                "recent_summary": data.recent_summary,
            },
            response_schema=_intent_schema(),
            max_tokens=1200,
        )
    )
    return RouteDecision(
        target=WorkflowTarget(payload["workflow"]),
        confidence=RouteConfidence(payload["confidence"]),
        slots=payload.get("slots", {}),
        clarification=payload.get("clarification", ""),
        reason=payload.get("reason", ""),
    )


def _workflow_catalog() -> JsonObject:
    return {
        "visualization": {
            "purpose": "Render PNG workout charts from natural-language requests.",
            "examples": [
                "piirrä viimeisimmästä treenistä sykealuejakauma",
                "draw latest heart-rate chart",
                "piirrä sama piirakkakuviona jakauma prosentuaalisesti",
                "vertaa kahta viimeisintä treeniä kuvaajana",
                "piirrä somekuva viimeisestä treenistä",
            ],
        },
        "workout_chat": {
            "purpose": "Answer coaching or analysis questions about stored workout facts without rendering an image.",
            "examples": ["miten viimeisin treeni meni", "analyze my latest run"],
        },
        "workout_management": {
            "purpose": "Slash-command workout listing, showing, deleting, active workout, and HR-zone management.",
        },
        "gpx_ingest": {
            "purpose": "Handle GPX attachments.",
        },
        "chat": {
            "purpose": "General conversation only when no specialized workflow applies.",
        },
    }


def extract_workout_reference(gateway: LLMGateway, data: WorkoutReferenceInput) -> WorkoutReference:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.WORKOUT_REFERENCE_EXTRACTION,
            system_prompt=(
                "Resolve a workout reference. Preserve explicit latest and active selectors. "
                "Set set_current_workout true only when the user is concretely referring to one workout that should "
                "become the current workout context for later requests. Do not set it for general workout discussion."
            ),
            user_payload={
                "user_text": data.user_text,
                "candidate_workouts": list(data.candidate_workouts),
                "active_workout": data.active_workout,
            },
            response_schema=_workout_reference_schema(),
            max_tokens=1200,
        )
    )
    return WorkoutReference(
        selector_type=payload["selector_type"],
        selector_value=payload["selector_value"],
        matched_workout_ids=tuple(payload.get("matched_workout_ids", ())),
        ambiguity_reason=payload.get("ambiguity_reason", ""),
        requires_clarification=payload["requires_clarification"],
        set_current_workout=payload.get("set_current_workout", False),
    )


def interpret_period_request(gateway: LLMGateway, data: PeriodRequestInput) -> PeriodRequest:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.PERIOD_REQUEST_INTERPRETATION,
            system_prompt=(
                "Interpret whether the user asks about a set or period of workouts. Return structured JSON only. "
                "Use scope_type none when the request is general conversation or clearly about one workout. "
                "Use all_workouts for requests covering the user's complete stored workout set. "
                "Use relative period selectors such as current_week, last_week, current_month, last_month, "
                "rolling_days, date_range, or calendar_year_to_date when the language asks for a period. "
                "Map user-language metric names to canonical metric ids from allowed_metrics. "
                "Do not calculate totals, query data, or infer ownership. Python resolves dates, filters, data access, "
                "aggregation, validation, and rendering."
            ),
            user_payload={
                "user_text": data.user_text,
                "current_datetime": data.current_datetime,
                "timezone": data.timezone,
                "allowed_scope_types": list(PERIOD_SCOPE_TYPES),
                "allowed_metrics": list(PERIOD_METRICS),
                "allowed_groupings": list(PERIOD_GROUPINGS),
                "allowed_output_modes": list(PERIOD_OUTPUT_MODES),
                "allowed_comparison_modes": list(PERIOD_COMPARISON_MODES),
                "compact_routing_context": data.compact_routing_context,
            },
            response_schema=_period_request_schema(),
            max_tokens=1600,
        )
    )
    return PeriodRequest(
        scope_type=payload["scope_type"],
        scope_value=payload["scope_value"],
        start_date=payload.get("start_date", ""),
        end_date=payload.get("end_date", ""),
        rolling_days=payload.get("rolling_days"),
        filters=payload.get("filters", {}),
        metrics=tuple(payload.get("metrics", ())),
        grouping=payload["grouping"],
        output_mode=payload["output_mode"],
        comparison_mode=payload["comparison_mode"],
        reason=payload.get("reason", ""),
    )


def write_period_analysis_reply(
    gateway: LLMGateway,
    data: PeriodAnalysisReplyInput,
    *,
    language: SupportedLanguage,
) -> PeriodAnalysisReply:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.PERIOD_ANALYSIS_REPLY,
            system_prompt=(
                f"Write a concise grounded workout period summary. Respond in {language.value}. "
                "Use period_facts as ground truth. Do not invent workouts, metrics, dates, or comparisons."
            ),
            user_payload={
                "user_text": data.user_text,
                "period_facts": data.period_facts,
                "bounded_recent_context": list(data.bounded_recent_context),
            },
            response_schema=_period_analysis_reply_schema(),
            max_tokens=2000,
        )
    )
    return PeriodAnalysisReply(
        reply_text=payload["reply_text"],
        claims_used=tuple(payload.get("claims_used", ())),
        missing_data_notes=tuple(payload.get("missing_data_notes", ())),
    )


def write_chat_reply(gateway: LLMGateway, data: ChatReplyInput, *, language: SupportedLanguage) -> ChatReply:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.CHAT_REPLY,
            system_prompt=(
                f"Write a concise Aimo reply. Respond in {language.value}. "
                "Use workflow_facts and capabilities as ground truth. "
                "Do not claim integrations, tools, or data access that are not present in the payload. "
                "If a request belongs to a slash command or private workflow, guide the user to that command."
            ),
            user_payload={
                "user_text": data.user_text,
                "bounded_recent_context": list(data.bounded_recent_context),
                "channel_summary": data.channel_summary,
                "profile_facts": data.profile_facts,
                "workflow_facts": data.workflow_facts,
            },
            response_schema=_chat_reply_schema(),
            max_tokens=2000,
        )
    )
    return ChatReply(
        reply_text=payload["reply_text"],
        tone=payload["tone"],
        should_update_summary=payload["should_update_summary"],
    )


def write_workout_reply(gateway: LLMGateway, data: WorkoutReplyInput, *, language: SupportedLanguage) -> WorkoutReply:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.WORKOUT_REPLY,
            system_prompt=f"Write a concise grounded workout coaching reply. Respond in {language.value}.",
            user_payload={
                "user_text": data.user_text,
                "resolved_workout_facts": data.resolved_workout_facts,
                "missing_data_facts": list(data.missing_data_facts),
                "profile_facts": data.profile_facts,
                "bounded_recent_context": list(data.bounded_recent_context),
            },
            response_schema=_workout_reply_schema(),
            max_tokens=2000,
        )
    )
    return WorkoutReply(
        reply_text=payload["reply_text"],
        claims_used=tuple(payload.get("claims_used", ())),
        missing_data_notes=tuple(payload.get("missing_data_notes", ())),
    )


def extract_visualization_intent(gateway: LLMGateway, data: VisualizationIntentInput) -> VisualizationIntent:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.VISUALIZATION_INTENT,
            system_prompt=(
                "Extract visualization intent only. Do not request workout point data. "
                "Use only canonical enum values from the response schema. "
                "Map aliases such as syke/heart_rate/hr to heart_rate_bpm and aika/time to elapsed_s. "
                "previous_visualization may be present for context. Use it only when the user refers to the previous, "
                "same, or current chart, or asks to refine/change/add to it. In that case return a complete new intent "
                "by reusing unchanged previous selector, metrics, transforms, chart_kind, and layout hints where appropriate. "
                "Use layout_mode auto by default. Use single_axis only when the user explicitly asks for the same y-axis, "
                "same scale, or overlaid series. Finnish 'samaan kuvaajaan' means the same image, not necessarily one axis. "
                "Use normalize_to_primary_range only for explicit scale/normalize/skaala requests, not merely for same image. "
                "Use as_percentage_of_total for percentage/share/osuus/prosentuaalinen part-to-total requests. "
                "Set chart_kind to pie only when the user explicitly asks for a pie/piirakka chart. "
                "Set chart_kind to map and requested_metrics to route only when the user explicitly asks for a route map, "
                "route plot, or map background visualization. "
                "Set output_mode to social_image for shareable/social workout images such as Finnish somekuva. "
                "For social_image, select exactly one workout, include route in requested_metrics, and include any explicitly "
                "requested stat metrics such as distance_km, duration_s, avg_hr_bpm, or ascent_m. "
                "For workout set or period requests, return a period selector such as current_month, last_week, "
                "rolling_days, date_range, all_workouts, or calendar_year_to_date; do not return an empty single-workout "
                "date selector for a period request. Python resolves dates, ownership, aggregation, and rendering. "
                "Set context_update.set_current_workout true only when the request concretely selects one workout "
                "that should become the current workout context for later requests."
            ),
            user_payload={
                "user_text": data.user_text,
                "compact_routing_context": data.compact_routing_context,
                "previous_visualization": data.previous_visualization or {},
            },
            response_schema=_visualization_intent_schema(),
            max_tokens=2000,
        )
    )
    return _visualization_intent_from_payload(payload)


def revise_visualization_intent(gateway: LLMGateway, data: VisualizationIntentRevisionInput) -> VisualizationIntent:
    payload = gateway.run(
        LLMRequest(
            operation=LLMOperation.VISUALIZATION_INTENT_REVISION,
            system_prompt=(
                "Revise the failed visualization intent into one complete valid intent. "
                "Use only dataset_manifest columns and allowed_primitives. "
                "Do not invent metrics, transforms, chart kinds, datasets, or metric-specific rendering behavior. "
                "Treat validation_errors as the source of what must be fixed. "
                "Return a full replacement intent, not a patch."
            ),
            user_payload={
                "user_text": data.user_text,
                "failed_intent": data.failed_intent,
                "validation_errors": list(data.validation_errors),
                "dataset_manifest": data.dataset_manifest,
                "allowed_primitives": data.allowed_primitives,
                "previous_visualization": data.previous_visualization or {},
            },
            response_schema=_visualization_intent_schema(),
            max_tokens=2000,
        )
    )
    return _visualization_intent_from_payload(payload)


def _visualization_intent_from_payload(payload: JsonObject) -> VisualizationIntent:
    return VisualizationIntent(
        workout_selector=payload["workout_selector"],
        x_metric=payload["x_metric"],
        y_metrics=tuple(payload.get("requested_metrics", payload.get("y_metrics", ()))),
        transforms=tuple(payload.get("transform_hints", payload.get("transforms", ()))),
        date_range=payload.get("date_range", {}),
        comparison_mode=payload.get("comparison_mode", ""),
        layout_mode=payload.get("layout_mode", "auto"),
        chart_kind=payload.get("chart_kind", "auto"),
        context_update=payload.get("context_update", {}),
        route_color_metric=payload.get("route_color_metric", ""),
        route_color_ignored_metrics=tuple(payload.get("route_color_ignored_metrics", ())),
        render_width=int(payload.get("render_width") or 0),
        render_height=int(payload.get("render_height") or 0),
        output_mode=payload.get("output_mode", "chart"),
    )


def _intent_schema() -> JsonObject:
    return {
        "required": ["workflow", "confidence", "slots", "clarification", "reason"],
        "properties": {
            "workflow": {"type": "string", "enum": [target.value for target in WorkflowTarget]},
            "confidence": {"type": "string", "enum": [confidence.value for confidence in RouteConfidence]},
            "slots": {"type": "object"},
            "clarification": {"type": "string"},
            "reason": {"type": "string"},
        },
    }


def _workout_reference_schema() -> JsonObject:
    return {
        "required": [
            "selector_type",
            "selector_value",
            "matched_workout_ids",
            "ambiguity_reason",
            "requires_clarification",
            "set_current_workout",
        ],
        "properties": {
            "selector_type": {"type": "string"},
            "selector_value": {"type": "string"},
            "matched_workout_ids": {"type": "array", "items": {"type": "string"}},
            "ambiguity_reason": {"type": "string"},
            "requires_clarification": {"type": "boolean"},
            "set_current_workout": {"type": "boolean"},
        },
    }


def _period_request_schema() -> JsonObject:
    return {
        "required": [
            "scope_type",
            "scope_value",
            "start_date",
            "end_date",
            "rolling_days",
            "filters",
            "metrics",
            "grouping",
            "output_mode",
            "comparison_mode",
            "reason",
        ],
        "properties": {
            "scope_type": {"type": "string", "enum": list(PERIOD_SCOPE_TYPES)},
            "scope_value": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "rolling_days": {"type": ["integer", "null"]},
            "filters": {
                "type": "object",
                "required": ["kind", "primary_kind", "tags"],
                "properties": {
                    "kind": {"type": "string"},
                    "primary_kind": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "metrics": {"type": "array", "items": {"type": "string", "enum": list(PERIOD_METRICS)}},
            "grouping": {"type": "string", "enum": list(PERIOD_GROUPINGS)},
            "output_mode": {"type": "string", "enum": list(PERIOD_OUTPUT_MODES)},
            "comparison_mode": {"type": "string", "enum": list(PERIOD_COMPARISON_MODES)},
            "reason": {"type": "string"},
        },
    }


def _period_analysis_reply_schema() -> JsonObject:
    return {
        "required": ["reply_text", "claims_used", "missing_data_notes"],
        "properties": {
            "reply_text": {"type": "string"},
            "claims_used": {"type": "array", "items": {"type": "string"}},
            "missing_data_notes": {"type": "array", "items": {"type": "string"}},
        },
    }


def _chat_reply_schema() -> JsonObject:
    return {
        "required": ["reply_text", "tone", "should_update_summary"],
        "properties": {
            "reply_text": {"type": "string"},
            "tone": {"type": "string"},
            "should_update_summary": {"type": "boolean"},
        },
    }


def _workout_reply_schema() -> JsonObject:
    return {
        "required": ["reply_text", "claims_used", "missing_data_notes"],
        "properties": {
            "reply_text": {"type": "string"},
            "claims_used": {"type": "array", "items": {"type": "string"}},
            "missing_data_notes": {"type": "array", "items": {"type": "string"}},
        },
    }


def _visualization_intent_schema() -> JsonObject:
    return {
        "required": [
            "workout_selector",
            "x_metric",
            "requested_metrics",
            "transform_hints",
            "date_range",
            "comparison_mode",
            "layout_mode",
            "chart_kind",
            "output_mode",
            "context_update",
        ],
        "properties": {
            "workout_selector": {
                "type": "object",
                "required": ["type", "value", "count", "limit"],
                "properties": {
                    "type": {"type": "string", "enum": list(VISUALIZATION_SELECTOR_TYPES)},
                    "value": {"type": "string"},
                    "count": {"type": ["integer", "null"]},
                    "limit": {"type": ["integer", "null"]},
                },
                "additionalProperties": False,
            },
            "x_metric": {"type": "string", "enum": list(VISUALIZATION_METRICS)},
            "requested_metrics": {
                "type": "array",
                "items": {"type": "string", "enum": list(VISUALIZATION_METRICS)},
            },
            "transform_hints": {
                "type": "array",
                "items": {"type": "string", "enum": list(VISUALIZATION_TRANSFORMS)},
            },
            "date_range": {
                "type": "object",
                "required": ["start", "end"],
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "comparison_mode": {"type": "string"},
            "layout_mode": {"type": "string", "enum": list(VISUALIZATION_LAYOUT_MODES)},
            "chart_kind": {"type": "string", "enum": list(VISUALIZATION_CHART_KINDS)},
            "output_mode": {"type": "string", "enum": list(VISUALIZATION_OUTPUT_MODES)},
            "context_update": {
                "type": "object",
                "required": ["set_current_workout"],
                "properties": {
                    "set_current_workout": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
    }
