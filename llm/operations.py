from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.i18n import SupportedLanguage
from core.routing import RouteConfidence, RouteDecision, WorkflowTarget
from llm.gateway import LLMGateway, LLMOperation, LLMRequest


JsonObject = dict[str, Any]
VISUALIZATION_SELECTOR_TYPES = ("latest", "active", "id", "date", "text", "list_index")
VISUALIZATION_METRICS = (
    "elapsed_s",
    "distance_km",
    "elevation_m",
    "heart_rate_bpm",
    "cadence_spm",
    "pace_s_per_km",
    "heart_rate_zone_seconds",
    "duration_s",
    "ascent_m",
    "avg_hr_bpm",
    "max_hr_bpm",
    "point_count",
)
VISUALIZATION_TRANSFORMS = (
    "normalize_to_primary_range",
    "rolling_average",
    "aggregate_sum",
    "aggregate_avg",
    "as_percentage_of_total",
)
VISUALIZATION_LAYOUT_MODES = ("auto", "single_axis", "small_multiples")
VISUALIZATION_CHART_KINDS = ("auto", "line", "bar", "pie")


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
            max_tokens=300,
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
