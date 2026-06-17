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
    WORKOUT_DELETE_PENDING = "workout.delete_pending"
    WORKOUT_DELETE_CONFIRMATION_INVALID = "workout.delete_confirmation_invalid"
    WORKOUT_DELETE_CONFIRMATION_EXPIRED = "workout.delete_confirmation_expired"
    WORKOUT_DELETE_CANCELLED = "workout.delete_cancelled"
    WORKOUT_DELETED = "workout.deleted"
    HR_ZONES_EMPTY = "hr_zones.empty"
    HR_ZONES_INVALID = "hr_zones.invalid"
    HR_ZONES_SUMMARY = "hr_zones.summary"
    HR_ZONES_UPDATED = "hr_zones.updated"
    GPX_ACCEPTED = "gpx.accepted"
    GPX_DUPLICATE = "gpx.duplicate"
    GPX_REJECTED = "gpx.rejected"
    VISUALIZATION_WORKING = "visualization.working"
    VISUALIZATION_CREATED = "visualization.created"
    VISUALIZATION_ROUTE_COLOR_LIMITED = "visualization.route_color_limited"
    ERROR_UNSUPPORTED_ATTACHMENT = "error.unsupported_attachment"
    ERROR_INVALID_GPX = "error.invalid_gpx"
    ERROR_NO_MATCHING_WORKOUT = "error.no_matching_workout"
    ERROR_MISSING_METRIC = "error.missing_metric"
    ERROR_AMBIGUOUS_WORKOUT = "error.ambiguous_workout"
    ERROR_NO_WORKOUTS_IN_PERIOD = "error.no_workouts_in_period"
    ERROR_PERIOD_REQUEST_INVALID = "error.period_request_invalid"
    ERROR_VISUALIZATION_PLAN_INVALID = "error.visualization_plan_invalid"
    ERROR_RENDER_FAILED = "error.render_failed"
    ERROR_MODEL_UNAVAILABLE = "error.model_unavailable"
    ERROR_PERMISSION_DENIED = "error.permission_denied"
    ERROR_STORAGE_ERROR = "error.storage_error"
    ERROR_UNEXPECTED = "error.unexpected"


Catalog = dict[TranslationKey, str]


CATALOGS: dict[SupportedLanguage, Catalog] = {
    SupportedLanguage.FI: {
        TranslationKey.HELP_INTRO: (
            "Osaan jutella lyhyesti, tallentaa GPX-treenejä, näyttää ja hallita treenejä sekä piirtää "
            "treenikuvaajia.\n"
            "- Lähetä GPX-liite maininnan tai /aimo-komennon kanssa.\n"
            "- Käytä /treenit: listaa, näytä, aseta aktiivinen, poista ja sykerajat.\n"
            "- Pyydä luonnollisesti: esimerkiksi \"analysoi viimeisin treeni\" tai \"piirrä syke ajan funktiona\".\n"
            "- /debug näyttää rajatun debug-jäljen.\n"
            "Välitän kielimallille vain pyynnön kannalta tarpeellisen rajatun kontekstin, en raakaa GPX-dataa "
            "tai kokonaisia pistejoukkoja."
        ),
        TranslationKey.CLARIFY_GENERIC: "Tarvitsen vielä tarkennuksen ennen kuin voin jatkaa.",
        TranslationKey.WORKFLOW_ACCEPTED: "Selvä, käsittelen pyynnön.",
        TranslationKey.WORKFLOW_NOOP: "Tällä pyynnöllä ei ollut tehtävää toimenpidettä.",
        TranslationKey.WORKOUT_NOT_FOUND: "En löytänyt tuolla viitteellä treeniä.",
        TranslationKey.WORKOUT_AMBIGUOUS: "Löysin useamman sopivan treenin. Tarkennatko, mitä niistä tarkoitat?",
        TranslationKey.WORKOUT_MISSING_METRIC: "Treenissä ei ole pyydettyä mittaria: {metric}.",
        TranslationKey.WORKOUT_LIST_EMPTY: "Sinulla ei ole vielä tallennettuja treenejä.",
        TranslationKey.WORKOUT_LIST_SUMMARY: "Löysin {count}:\n{items}",
        TranslationKey.WORKOUT_DETAILS: (
            "{title}\n"
            "Aika: {date}\n"
            "Laji: {kind}\n"
            "Matka: {distance_km} km\n"
            "Kesto: {duration}\n"
            "Keskisyke: {avg_hr}\n"
            "Nousu: {ascent}"
        ),
        TranslationKey.WORKOUT_ACTIVE_EMPTY: "Sinulla ei ole aktiivista treeniä.",
        TranslationKey.WORKOUT_ACTIVE_SET: "Asetin aktiiviseksi treeniksi: {title}.",
        TranslationKey.WORKOUT_DELETE_PENDING: (
            "Poisto vaatii vahvistuksen.\n"
            "Poistettava treeni: {title}\n"
            "Vahvista tai peruuta poisto painikkeella 60 sekunnin sisällä."
        ),
        TranslationKey.WORKOUT_DELETE_CONFIRMATION_INVALID: (
            "Poiston vahvistus ei täsmää. Aloita poisto uudelleen /treenit poista -komennolla."
        ),
        TranslationKey.WORKOUT_DELETE_CONFIRMATION_EXPIRED: (
            "Poiston vahvistus vanheni. Aloita poisto uudelleen /treenit poista -komennolla."
        ),
        TranslationKey.WORKOUT_DELETE_CANCELLED: "Peruin poiston.",
        TranslationKey.WORKOUT_DELETED: "Poistin treenin: {title}.",
        TranslationKey.HR_ZONES_EMPTY: "Sinulle ei ole vielä asetettu sykerajoja.",
        TranslationKey.HR_ZONES_INVALID: (
            "Sykerajojen muoto ei kelpaa. Anna maksimisyke tai viisi nousevaa ylärajaa, "
            "esim. 190 tai 114,133,152,171,190."
        ),
        TranslationKey.HR_ZONES_SUMMARY: "Sykerajasi:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Päivitin sykerajat.",
        TranslationKey.GPX_ACCEPTED: "Tallensin GPX-tiedoston {filename} treeniksi: {title}.",
        TranslationKey.GPX_DUPLICATE: "GPX-tiedosto {filename} on jo tallennettu treeniksi: {title}.",
        TranslationKey.GPX_REJECTED: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta: {filename}.",
        TranslationKey.VISUALIZATION_WORKING: "Työstän visualisointia...",
        TranslationKey.VISUALIZATION_CREATED: "Piirsin kuvaajan treenistä: {title}.",
        TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED: (
            "Kartalla voi korostaa vain yhtä data-arvoa kerrallaan. Valitsin ensimmäisen: {metric}."
        ),
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "Tuo liitetyyppi ei ole tuettu.",
        TranslationKey.ERROR_INVALID_GPX: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "En löytänyt pyynnölle sopivaa treeniä.",
        TranslationKey.ERROR_MISSING_METRIC: "Treenistä puuttuu tarvittava mittari: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "Löysin useamman mahdollisen treenin. Tarvitsen tarkemman viitteen.",
        TranslationKey.ERROR_NO_WORKOUTS_IN_PERIOD: "En löytänyt treenejä pyydetyltä jaksolta.",
        TranslationKey.ERROR_PERIOD_REQUEST_INVALID: "En saanut muodostettua kelvollista treenijakson rajausta.",
        TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID: "En saanut muodostettua kelvollista kuvaajasuunnitelmaa.",
        TranslationKey.ERROR_RENDER_FAILED: "Kuvaajan piirtäminen epäonnistui.",
        TranslationKey.ERROR_MODEL_UNAVAILABLE: "Kielimalli ei ole juuri nyt käytettävissä.",
        TranslationKey.ERROR_PERMISSION_DENIED: "Sinulla ei ole oikeutta tähän toimintoon.",
        TranslationKey.ERROR_STORAGE_ERROR: "Tietojen tallennus tai haku epäonnistui.",
        TranslationKey.ERROR_UNEXPECTED: "Tapahtui odottamaton virhe.",
    },
    SupportedLanguage.EN: {
        TranslationKey.HELP_INTRO: (
            "I can chat briefly, store GPX workouts, show and manage workouts, and draw workout charts.\n"
            "- Send a GPX attachment with a mention or /aimo.\n"
            "- Use /treenit to list, inspect, activate, delete, and configure heart-rate zones.\n"
            "- Ask naturally, for example \"analyze my latest workout\" or \"draw heart rate over time\".\n"
            "- /debug shows the latest bounded debug trace.\n"
            "I only send the language model the bounded context needed for the request, not raw GPX data "
            "or full point arrays."
        ),
        TranslationKey.CLARIFY_GENERIC: "I need one clarification before I can continue.",
        TranslationKey.WORKFLOW_ACCEPTED: "Got it, I will handle the request.",
        TranslationKey.WORKFLOW_NOOP: "There was nothing to do for that request.",
        TranslationKey.WORKOUT_NOT_FOUND: "I could not find a workout with that reference.",
        TranslationKey.WORKOUT_AMBIGUOUS: "I found several matching workouts. Which one did you mean?",
        TranslationKey.WORKOUT_MISSING_METRIC: "The workout does not contain the requested metric: {metric}.",
        TranslationKey.WORKOUT_LIST_EMPTY: "You do not have any saved workouts yet.",
        TranslationKey.WORKOUT_LIST_SUMMARY: "I found {count}:\n{items}",
        TranslationKey.WORKOUT_DETAILS: (
            "{title}\n"
            "Time: {date}\n"
            "Kind: {kind}\n"
            "Distance: {distance_km} km\n"
            "Duration: {duration}\n"
            "Avg HR: {avg_hr}\n"
            "Ascent: {ascent}"
        ),
        TranslationKey.WORKOUT_ACTIVE_EMPTY: "You do not have an active workout.",
        TranslationKey.WORKOUT_ACTIVE_SET: "Set active workout to: {title}.",
        TranslationKey.WORKOUT_DELETE_PENDING: (
            "Deletion requires confirmation.\n"
            "Workout to delete: {title}\n"
            "Confirm or cancel deletion with the buttons within 60 seconds."
        ),
        TranslationKey.WORKOUT_DELETE_CONFIRMATION_INVALID: (
            "The delete confirmation did not match. Start deletion again with /treenit poista."
        ),
        TranslationKey.WORKOUT_DELETE_CONFIRMATION_EXPIRED: (
            "The delete confirmation expired. Start deletion again with /treenit poista."
        ),
        TranslationKey.WORKOUT_DELETE_CANCELLED: "Cancelled deletion.",
        TranslationKey.WORKOUT_DELETED: "Deleted workout: {title}.",
        TranslationKey.HR_ZONES_EMPTY: "You do not have heart-rate zones configured yet.",
        TranslationKey.HR_ZONES_INVALID: (
            "The heart-rate zone format is invalid. Provide max heart rate or five increasing upper limits, "
            "for example 190 or 114,133,152,171,190."
        ),
        TranslationKey.HR_ZONES_SUMMARY: "Your heart-rate zones:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Updated heart-rate zones.",
        TranslationKey.GPX_ACCEPTED: "Saved GPX file {filename} as workout: {title}.",
        TranslationKey.GPX_DUPLICATE: "GPX file {filename} is already saved as workout: {title}.",
        TranslationKey.GPX_REJECTED: "That attachment does not look like a valid GPX file: {filename}.",
        TranslationKey.VISUALIZATION_WORKING: "Working on the visualization...",
        TranslationKey.VISUALIZATION_CREATED: "I drew the chart for workout: {title}.",
        TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED: (
            "A route map can highlight only one data value at a time. I used the first one: {metric}."
        ),
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "That attachment type is not supported.",
        TranslationKey.ERROR_INVALID_GPX: "That attachment does not look like a valid GPX file.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "I could not find a workout matching the request.",
        TranslationKey.ERROR_MISSING_METRIC: "The workout is missing a required metric: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "I found several possible workouts. I need a more specific reference.",
        TranslationKey.ERROR_NO_WORKOUTS_IN_PERIOD: "I did not find workouts in the requested period.",
        TranslationKey.ERROR_PERIOD_REQUEST_INVALID: "I could not build a valid workout-period selection.",
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
