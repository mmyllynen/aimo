from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.errors import AppError, ErrorCategory
from core.events import CanonicalEvent
from core.i18n import TranslationKey
from core.routing import RouteDecision
from core.workflows import OutgoingKind, OutgoingMessage, WorkflowResult, WorkflowStatus
from storage.unit_of_work import RepositoryBundle
from workflows.workout_management import parse_zone_upper_limits, zone_line, zones_from_upper_limits


SUPPORTED_ACTIONS = {"nayta", "sykerajat"}


@dataclass(frozen=True)
class SettingsWorkflow:
    def handle(
        self,
        event: CanonicalEvent,
        route: RouteDecision,
        repositories: RepositoryBundle,
    ) -> WorkflowResult:
        del route
        options = _options(event)
        action = str(event.metadata.get("subcommand", "")).strip().lower()
        if action not in SUPPORTED_ACTIONS:
            action = "nayta"
        if action == "sykerajat":
            return self._set_hr_zones(event, repositories, options.get("zones"))
        return self._show(event, repositories)

    def _show(self, event: CanonicalEvent, repositories: RepositoryBundle) -> WorkflowResult:
        zones = repositories.heart_rate_zones.list_for_user(event.user_id)
        if zones:
            settings = "Sykerajat:\n" + "\n".join(zone_line(zone) for zone in zones)
        else:
            settings = "Sykerajat: ei asetettu."
        return _message(TranslationKey.SETTINGS_SUMMARY, settings=settings)

    def _set_hr_zones(
        self,
        event: CanonicalEvent,
        repositories: RepositoryBundle,
        zones_payload: Any,
    ) -> WorkflowResult:
        upper_limits = parse_zone_upper_limits(zones_payload)
        if upper_limits is None or not upper_limits:
            return _user_error(TranslationKey.HR_ZONES_INVALID, ErrorCategory.UNEXPECTED)
        repositories.heart_rate_zones.replace_for_user(
            event.user_id,
            zones_from_upper_limits(event.user_id, upper_limits),
        )
        return _message(TranslationKey.HR_ZONES_UPDATED)


def _options(event: CanonicalEvent) -> dict[str, Any]:
    options = event.metadata.get("options", {})
    if isinstance(options, dict):
        return options
    return {}


def _message(key: TranslationKey, **params: Any) -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.SUCCESS,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.EPHEMERAL_TEXT,
                text_key=key.value,
                text_params=params,
            ),
        ),
    )


def _user_error(key: TranslationKey, category: ErrorCategory) -> WorkflowResult:
    return WorkflowResult(
        status=WorkflowStatus.USER_ERROR,
        messages=(
            OutgoingMessage(
                kind=OutgoingKind.EPHEMERAL_TEXT,
                text_key=key.value,
            ),
        ),
        error=AppError(
            category=category,
            message=key.value,
            user_message_key=key.value,
        ),
    )
