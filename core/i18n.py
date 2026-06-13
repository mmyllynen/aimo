from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from string import Formatter
from typing import Any


class SupportedLanguage(StrEnum):
    FI = "fi"
    EN = "en"


DEFAULT_LANGUAGE = SupportedLanguage.FI


class TranslationKey(StrEnum):
    HELP_INTRO = "help.intro"
    HELP_UPLOAD_GPX = "help.upload_gpx"
    HELP_WORKOUTS = "help.workouts"
    HELP_VISUALIZATION = "help.visualization"
    HELP_DEBUG = "help.debug"
    CLARIFY_GENERIC = "clarify.generic"
    WORKFLOW_ACCEPTED = "workflow.accepted"
    WORKFLOW_NOOP = "workflow.noop"
    WORKOUT_NOT_FOUND = "workout.not_found"
    WORKOUT_AMBIGUOUS = "workout.ambiguous"
    WORKOUT_MISSING_METRIC = "workout.missing_metric"
    WORKOUT_LIST_EMPTY = "workout.list_empty"
    WORKOUT_LIST_SUMMARY = "workout.list_summary"
    WORKOUT_DETAILS = "workout.details"
    WORKOUT_ACTIVE_EMPTY = "workout.active_empty"
    WORKOUT_ACTIVE_SET = "workout.active_set"
    WORKOUT_DELETED = "workout.deleted"
    HR_ZONES_EMPTY = "hr_zones.empty"
    HR_ZONES_SUMMARY = "hr_zones.summary"
    HR_ZONES_UPDATED = "hr_zones.updated"
    GPX_ACCEPTED = "gpx.accepted"
    GPX_DUPLICATE = "gpx.duplicate"
    GPX_REJECTED = "gpx.rejected"
    VISUALIZATION_CREATED = "visualization.created"
    ERROR_UNSUPPORTED_ATTACHMENT = "error.unsupported_attachment"
    ERROR_INVALID_GPX = "error.invalid_gpx"
    ERROR_NO_MATCHING_WORKOUT = "error.no_matching_workout"
    ERROR_MISSING_METRIC = "error.missing_metric"
    ERROR_AMBIGUOUS_WORKOUT = "error.ambiguous_workout"
    ERROR_VISUALIZATION_PLAN_INVALID = "error.visualization_plan_invalid"
    ERROR_RENDER_FAILED = "error.render_failed"
    ERROR_MODEL_UNAVAILABLE = "error.model_unavailable"
    ERROR_PERMISSION_DENIED = "error.permission_denied"
    ERROR_STORAGE_ERROR = "error.storage_error"
    ERROR_UNEXPECTED = "error.unexpected"


Catalog = dict[TranslationKey, str]


CATALOGS: dict[SupportedLanguage, Catalog] = {
    SupportedLanguage.FI: {
        TranslationKey.HELP_INTRO: "Voin jutella, tallentaa GPX-treenejä, hallita treenejä ja piirtää treenikuvaajia.",
        TranslationKey.HELP_UPLOAD_GPX: "Lähetä GPX-liite maininnan kanssa, niin tallennan sen treeniksi.",
        TranslationKey.HELP_WORKOUTS: "Käytä /treenit-komentoa treenien listaamiseen, tarkasteluun ja hallintaan.",
        TranslationKey.HELP_VISUALIZATION: "Voit pyytää kuvaajaa luonnollisella kielellä, esimerkiksi viimeisimmästä tai aktiivisesta treenistä.",
        TranslationKey.HELP_DEBUG: "/debug palauttaa viimeisimmän rajatun debug-jäljen.",
        TranslationKey.CLARIFY_GENERIC: "Tarvitsen vielä tarkennuksen ennen kuin voin jatkaa.",
        TranslationKey.WORKFLOW_ACCEPTED: "Selvä, käsittelen pyynnön.",
        TranslationKey.WORKFLOW_NOOP: "Tällä pyynnöllä ei ollut tehtävää toimenpidettä.",
        TranslationKey.WORKOUT_NOT_FOUND: "En löytänyt tuolla viitteellä treeniä.",
        TranslationKey.WORKOUT_AMBIGUOUS: "Löysin useamman sopivan treenin. Tarkennatko, mitä niistä tarkoitat?",
        TranslationKey.WORKOUT_MISSING_METRIC: "Treenissä ei ole pyydettyä mittaria: {metric}.",
        TranslationKey.WORKOUT_LIST_EMPTY: "Sinulla ei ole vielä tallennettuja treenejä.",
        TranslationKey.WORKOUT_LIST_SUMMARY: "Löysin {count} treeniä:\n{items}",
        TranslationKey.WORKOUT_DETAILS: "{title}\nPäivä: {date}\nMatka: {distance_km} km\nKesto: {duration}",
        TranslationKey.WORKOUT_ACTIVE_EMPTY: "Sinulla ei ole aktiivista treeniä.",
        TranslationKey.WORKOUT_ACTIVE_SET: "Asetin aktiiviseksi treeniksi: {title}.",
        TranslationKey.WORKOUT_DELETED: "Poistin treenin: {title}.",
        TranslationKey.HR_ZONES_EMPTY: "Sinulle ei ole vielä asetettu sykerajoja.",
        TranslationKey.HR_ZONES_SUMMARY: "Sykerajasi:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Päivitin sykerajat.",
        TranslationKey.GPX_ACCEPTED: "Tallensin GPX-tiedoston treeniksi: {title}.",
        TranslationKey.GPX_DUPLICATE: "Tämä GPX on jo tallennettu treeniksi: {title}.",
        TranslationKey.GPX_REJECTED: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta.",
        TranslationKey.VISUALIZATION_CREATED: "Piirsin kuvaajan treenistä: {title}.",
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "Tuo liitetyyppi ei ole tuettu.",
        TranslationKey.ERROR_INVALID_GPX: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "En löytänyt pyynnölle sopivaa treeniä.",
        TranslationKey.ERROR_MISSING_METRIC: "Treenistä puuttuu tarvittava mittari: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "Löysin useamman mahdollisen treenin. Tarvitsen tarkemman viitteen.",
        TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID: "En saanut muodostettua kelvollista kuvaajasuunnitelmaa.",
        TranslationKey.ERROR_RENDER_FAILED: "Kuvaajan piirtäminen epäonnistui.",
        TranslationKey.ERROR_MODEL_UNAVAILABLE: "Kielimalli ei ole juuri nyt käytettävissä.",
        TranslationKey.ERROR_PERMISSION_DENIED: "Sinulla ei ole oikeutta tähän toimintoon.",
        TranslationKey.ERROR_STORAGE_ERROR: "Tietojen tallennus tai haku epäonnistui.",
        TranslationKey.ERROR_UNEXPECTED: "Tapahtui odottamaton virhe.",
    },
    SupportedLanguage.EN: {
        TranslationKey.HELP_INTRO: "I can chat, store GPX workouts, manage workouts, and draw workout charts.",
        TranslationKey.HELP_UPLOAD_GPX: "Send a GPX attachment with a mention and I will save it as a workout.",
        TranslationKey.HELP_WORKOUTS: "Use /treenit to list, inspect, and manage workouts.",
        TranslationKey.HELP_VISUALIZATION: "You can ask for charts in natural language, for example from the latest or active workout.",
        TranslationKey.HELP_DEBUG: "/debug returns the latest bounded debug trace.",
        TranslationKey.CLARIFY_GENERIC: "I need one clarification before I can continue.",
        TranslationKey.WORKFLOW_ACCEPTED: "Got it, I will handle the request.",
        TranslationKey.WORKFLOW_NOOP: "There was nothing to do for that request.",
        TranslationKey.WORKOUT_NOT_FOUND: "I could not find a workout with that reference.",
        TranslationKey.WORKOUT_AMBIGUOUS: "I found several matching workouts. Which one did you mean?",
        TranslationKey.WORKOUT_MISSING_METRIC: "The workout does not contain the requested metric: {metric}.",
        TranslationKey.WORKOUT_LIST_EMPTY: "You do not have any saved workouts yet.",
        TranslationKey.WORKOUT_LIST_SUMMARY: "I found {count} workouts:\n{items}",
        TranslationKey.WORKOUT_DETAILS: "{title}\nDate: {date}\nDistance: {distance_km} km\nDuration: {duration}",
        TranslationKey.WORKOUT_ACTIVE_EMPTY: "You do not have an active workout.",
        TranslationKey.WORKOUT_ACTIVE_SET: "Set active workout to: {title}.",
        TranslationKey.WORKOUT_DELETED: "Deleted workout: {title}.",
        TranslationKey.HR_ZONES_EMPTY: "You do not have heart-rate zones configured yet.",
        TranslationKey.HR_ZONES_SUMMARY: "Your heart-rate zones:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Updated heart-rate zones.",
        TranslationKey.GPX_ACCEPTED: "Saved the GPX file as a workout: {title}.",
        TranslationKey.GPX_DUPLICATE: "This GPX is already saved as workout: {title}.",
        TranslationKey.GPX_REJECTED: "That attachment does not look like a valid GPX file.",
        TranslationKey.VISUALIZATION_CREATED: "I drew the chart for workout: {title}.",
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "That attachment type is not supported.",
        TranslationKey.ERROR_INVALID_GPX: "That attachment does not look like a valid GPX file.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "I could not find a workout matching the request.",
        TranslationKey.ERROR_MISSING_METRIC: "The workout is missing a required metric: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "I found several possible workouts. I need a more specific reference.",
        TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID: "I could not build a valid chart plan.",
        TranslationKey.ERROR_RENDER_FAILED: "Rendering the chart failed.",
        TranslationKey.ERROR_MODEL_UNAVAILABLE: "The language model is not available right now.",
        TranslationKey.ERROR_PERMISSION_DENIED: "You do not have permission for that action.",
        TranslationKey.ERROR_STORAGE_ERROR: "Reading or writing stored data failed.",
        TranslationKey.ERROR_UNEXPECTED: "An unexpected error occurred.",
    },
}


class I18nError(ValueError):
    pass


class UnsupportedLanguageError(I18nError):
    pass


class MissingTranslationError(I18nError):
    pass


@dataclass(frozen=True)
class LocalizationConfig:
    language: SupportedLanguage = DEFAULT_LANGUAGE


@dataclass(frozen=True)
class LocalizedText:
    key: TranslationKey
    params: dict[str, Any] = field(default_factory=dict)


class Translator:
    def __init__(self, language: SupportedLanguage = DEFAULT_LANGUAGE) -> None:
        self.language = language

    def text(self, key: TranslationKey | str, **params: Any) -> str:
        translation_key = parse_translation_key(key)
        template = CATALOGS[self.language].get(translation_key)
        if template is None:
            raise MissingTranslationError(f"Missing {self.language} translation for {translation_key}")
        try:
            return template.format(**params)
        except KeyError as exc:
            missing = exc.args[0]
            raise MissingTranslationError(
                f"Missing interpolation value {missing!r} for {self.language}:{translation_key}"
            ) from exc

    def render(self, localized: LocalizedText) -> str:
        return self.text(localized.key, **localized.params)


def parse_language(value: str | None) -> SupportedLanguage:
    normalized = (value or "").strip().lower()
    if not normalized:
        return DEFAULT_LANGUAGE
    try:
        return SupportedLanguage(normalized)
    except ValueError as exc:
        supported = ", ".join(language.value for language in SupportedLanguage)
        raise UnsupportedLanguageError(f"Unsupported language {value!r}; supported values: {supported}") from exc


def parse_translation_key(value: TranslationKey | str) -> TranslationKey:
    if isinstance(value, TranslationKey):
        return value
    try:
        return TranslationKey(value)
    except ValueError as exc:
        raise MissingTranslationError(f"Unknown translation key {value!r}") from exc


def load_localization_config(path: str | Path = "aimo.conf") -> LocalizationConfig:
    parser = ConfigParser()
    parser.read(path)
    language = parser.get("bot", "language", fallback=None)
    if language is None:
        language = parser.get("aimo", "language", fallback=None)
    return LocalizationConfig(language=parse_language(language))


def validate_catalogs() -> None:
    expected_keys = set(TranslationKey)
    for language, catalog in CATALOGS.items():
        missing_keys = expected_keys - set(catalog)
        extra_keys = set(catalog) - expected_keys
        if missing_keys:
            missing = ", ".join(sorted(key.value for key in missing_keys))
            raise MissingTranslationError(f"Missing {language} translations: {missing}")
        if extra_keys:
            extra = ", ".join(sorted(key.value for key in extra_keys))
            raise MissingTranslationError(f"Unknown {language} translations: {extra}")
        _validate_placeholders(language, catalog)


def _validate_placeholders(language: SupportedLanguage, catalog: Catalog) -> None:
    reference = CATALOGS[DEFAULT_LANGUAGE]
    formatter = Formatter()
    for key, template in catalog.items():
        current_fields = {field for _, field, _, _ in formatter.parse(template) if field}
        reference_fields = {field for _, field, _, _ in formatter.parse(reference[key]) if field}
        if current_fields != reference_fields:
            raise MissingTranslationError(
                f"Placeholder mismatch for {language}:{key}: {current_fields} != {reference_fields}"
            )
