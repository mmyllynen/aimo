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
    HELP_COMMANDS = "help.commands"
    HELP_PRIVACY = "help.privacy"
    HELP_VISUALIZATION = "help.visualization"
    HELP_SOCIAL_IMAGE = "help.social_image"
    HELP_UNKNOWN_TOPIC = "help.unknown_topic"
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
    WORKOUT_RENAMED = "workout.renamed"
    WORKOUT_TAG_ADDED = "workout.tag_added"
    WORKOUT_TAG_REMOVED = "workout.tag_removed"
    WORKOUT_TAG_INVALID = "workout.tag_invalid"
    SETTINGS_SUMMARY = "settings.summary"
    HR_ZONES_EMPTY = "hr_zones.empty"
    HR_ZONES_INVALID = "hr_zones.invalid"
    HR_ZONES_SUMMARY = "hr_zones.summary"
    HR_ZONES_UPDATED = "hr_zones.updated"
    GPX_ACCEPTED = "gpx.accepted"
    GPX_ACCEPTED_ROUTE = "gpx.accepted_route"
    GPX_DUPLICATE = "gpx.duplicate"
    GPX_DUPLICATE_ROUTE = "gpx.duplicate_route"
    GPX_REJECTED = "gpx.rejected"
    VISUALIZATION_WORKING = "visualization.working"
    VISUALIZATION_CREATED = "visualization.created"
    VISUALIZATION_ROUTE_COLOR_LIMITED = "visualization.route_color_limited"
    OVERLAY_ANIMATION_CREATED = "overlay_animation.created"
    OVERLAY_ANIMATION_CREATED_LINK = "overlay_animation.created_link"
    OVERLAY_ANIMATION_BUNDLE_CREATED = "overlay_animation.bundle_created"
    ERROR_UNSUPPORTED_ATTACHMENT = "error.unsupported_attachment"
    ERROR_INVALID_GPX = "error.invalid_gpx"
    ERROR_NO_MATCHING_WORKOUT = "error.no_matching_workout"
    ERROR_MISSING_METRIC = "error.missing_metric"
    ERROR_AMBIGUOUS_WORKOUT = "error.ambiguous_workout"
    ERROR_NO_WORKOUTS_IN_PERIOD = "error.no_workouts_in_period"
    ERROR_PERIOD_REQUEST_INVALID = "error.period_request_invalid"
    ERROR_VISUALIZATION_PLAN_INVALID = "error.visualization_plan_invalid"
    ERROR_SOCIAL_IMAGE_REQUIRES_ROUTE = "error.social_image_requires_route"
    ERROR_OVERLAY_ANIMATION_REQUIRES_ROUTE = "error.overlay_animation_requires_route"
    ERROR_OVERLAY_ANIMATION_ENCODER_UNAVAILABLE = "error.overlay_animation_encoder_unavailable"
    ERROR_RENDER_FAILED = "error.render_failed"
    ERROR_MODEL_UNAVAILABLE = "error.model_unavailable"
    ERROR_PERMISSION_DENIED = "error.permission_denied"
    ERROR_STORAGE_ERROR = "error.storage_error"
    ERROR_UNEXPECTED = "error.unexpected"


Catalog = dict[TranslationKey, str]


CATALOGS: dict[SupportedLanguage, Catalog] = {
    SupportedLanguage.FI: {
        TranslationKey.HELP_INTRO: (
            "**Aimo lyhyesti**\n"
            "Osaan vastata mainintoihin, tallentaa GPX-treenejä, hallita treenejä, jutella treeneistä ja piirtää kuvaajia.\n"
            "- Lähetä GPX-liite maininnan kanssa tai komennolla `/gpx tallenna liite`.\n"
            "- Kysy luonnollisesti: `@Aimo analysoi viimeisin treeni` tai `@Aimo piirrä syke ajan funktiona`.\n"
            "- Hallitse treenejä `/treenit`-komennoilla ja asetuksia `/asetukset`-komennoilla.\n"
            "- Piirrä reittejä, jakso-/trendikuvaajia ja somekuvia maininnalla.\n"
            "- En lähetä kielimallille raakaa GPX-dataa tai kokonaisia pistejoukkoja.\n"
            "**Help-aiheet:** `yleinen`, `komennot`, `visualisointi`, `somekuva`, `privacy`."
        ),
        TranslationKey.HELP_COMMANDS: (
            "**Komennot**\n"
            "- `/aimo syote` kysyy, juttelee treeneistä tai pyytää kuvaajan luonnollisella kielellä.\n"
            "- `/gpx tallenna liite nimi` tallentaa GPX:n; `nimi` on valinnainen.\n"
            "- `/help aihe` näyttää ohjeen: `yleinen`, `komennot`, `visualisointi`, `somekuva`, `privacy`.\n"
            "- `/treenit listaa` listaa treenit; `/treenit nayta viite` näyttää treenin ja asettaa sen nykyiseksi.\n"
            "- `/treenit aktiivinen` näyttää nykyisen; `/treenit aseta_aktiivinen viite` vaihtaa sen.\n"
            "- `/treenit nimea viite nimi`, `tagaa viite tagi`, `poista_tagi viite tagi` muokkaavat treeniä.\n"
            "- `/treenit poista viite` poistaa vasta 60 s painikevahvistuksen jälkeen.\n"
            "- `/asetukset nayta` näyttää asetukset; `/asetukset sykerajat zones` hyväksyy esim. `190` tai `114,133,152,171,190`.\n"
            "- `/debug level` palauttaa rajatun debug-jäljen. Maininnoissa `+debug0`, `+debug1` ja `+debug2` lisäävät debug-jäljen vastaukseen."
        ),
        TranslationKey.HELP_VISUALIZATION: (
            "**Visualisointi**\n"
            "Pyydä maininnalla: reittikartta, viiva/aikakuvaaja, pylväät, piirakka, jakso-/trendikuvaaja tai somekuva.\n"
            "- Treeniviite: viimeisin, aktiivinen, listanumero, päivämäärä, päiväväli, tagi, laji/tyyppi tai hakuteksti.\n"
            "- Jaksot: tämä/viime viikko, tämä/viime kuukausi, viimeiset N päivää, kaikki treenit, kuluva vuosi.\n"
            "- Koko: `+square`, `+portrait`, `+landscape`.\n"
            "- Mittarit: `+hr`/`+syke`, `+elevation`/`+korkeus`, `+pace`/`+vauhti`, `+distance`/`+matka`, `+duration`/`+kesto`, `+ascent`/`+nousu`/`+nousumetrit`, `+maxhr`/`+maksimisyke`, `+date`/`+paiva`/`+päivä`.\n"
            "- Plustägi `+sana` lisää, miinustägi `-sana` poistaa, tarkenne `avain=arvo` asettaa arvon; esim. `+hr`, `-waypoints`, `-korkeus`, `dim=45`.\n"
            "- Somekuva: `+social` tai `+somekuva`; presetit ja tarkenteet: `/help aihe:somekuva`.\n"
            "- Overlay-animaatio: `+overlay start=12.4km length=5s fps=10 size=1280x720 +map +speed +hr`; pyöreä Resolve-yhteensopiva kartta: `+overlay +map dist=12.4km duration=60s transparent=true layout=circle_map map_style=dark tile_alpha=0.9`.\n"
            "- Reittikartta voi korostaa yhden datamittarin kerrallaan: `+hr`, `+elevation` tai `+pace`.\n"
            "- Yhden reitin kartassa GPX-waypointit/reittimerkit ja km-markerit näytetään kartalla; waypointit näkyvät myös overlay-listassa. Poista waypointit `-waypoints` tai `-reittimerkit`.\n"
            "- Yhden reitin kartassa korkeuskäyrä, jyrkkyysvärit ja km-akseli näytetään alalaidassa, jos korkeustieto löytyy; poista ne `-elevation` tai `-korkeus`.\n"
            "**Esimerkit:** `@Aimo piirrä viimeisin treeni kartalle +hr`, `@Aimo näytä reitti kartalla -reittimerkit`, `@Aimo piirrä syke aktiivisesta treenistä +portrait`."
        ),
        TranslationKey.HELP_SOCIAL_IMAGE: (
            "**Somekuva**\n"
            "Perusmuoto: `@Aimo piirrä somekuva viimeisestä treenistä +distance +kesto +hr`. Liitetty kuva toimii taustana; muuten käytetään karttaa.\n"
            "- Presetit: `+classic`, `+minimal`, `+poster`, `+routeonly`, `+data`, `+photo`.\n"
            "- Koko/statit: `+square`, `+portrait`, `+landscape`, `+distance`, `+duration`/`+kesto`, `+hr`, `+maxhr`, `+pace`, `+ascent`, `+date`.\n"
            "- Tarkenne on `avain=arvo`, esim. `dim=45 route=white title=bottom`; kirjoita samalle riville tai `tyyli:`/`style:`-riville.\n"
            "- Tausta: `crop=center|top|bottom|left|right|X,Y`, `dim=0..70`, `blur=0..20`, `filter=none|warm|cool|bw|vivid|matte`.\n"
            "- Reitti: `route=default|auto|blue|white|black|red|green|yellow|#RRGGBB`, `route_size=small|normal|large|huge`, `route_shadow`/`markers`=`on|off|true|false|yes|no|1|0|kyllä|ei`, `route_pos=center|top|bottom|left|right`.\n"
            "- Teksti/data: `title=top|bottom|hide`, `title_align=left|center`, `stats=left|right|bottom|hide`, `stats_style=compact|large|stacked`, `panel=dark|light|none`, `text=white|black|#RRGGBB`, `accent=default|auto|blue|white|black|red|green|yellow|#RRGGBB`, `font=clean|bold|mono|serif`.\n"
            "- Aliakset: `darken/tummennus=dim`, `shadow/varjo=route_shadow`, `reitti/route_color=route`, `data=stats`, `paneeli=panel`, `teksti=text`.\n"
            "**Esimerkit:** `@Aimo piirrä somekuva viimeisestä treenistä +poster +distance +hr style: route=white dim=25 title=bottom`, `@Aimo piirrä somekuva viimeisestä treenistä +routeonly tyyli: crop=50,35 filter=bw route_size=huge markers=off`."
        ),
        TranslationKey.HELP_PRIVACY: (
            "**Tietosuoja ja tallennus**\n"
            "- Tallennan käyttäjätunnisteen, nimen/display namen, rajattua kanavahistoriaa, GPX-liitteiden metatiedot ja raakatiedoston, "
            "treenien yhteenvedot, treenipisteet, tagit, aktiivisen treenin, sykerajat, renderöidyt kuvat ja redaktoidut debug-jäljet.\n"
            "- Tietoja käytetään keskustelukontekstiin, treenien hallintaan, analyysiin, visualisointeihin ja virheiden selvitykseen.\n"
            "- Kielimallille annetaan vain pyynnön kannalta rajattu konteksti ja tiivistetyt treenifaktat; raakaa GPX-dataa, täysiä pistejoukkoja, "
            "kuvatavuja tai salaisuuksia ei lähetetä mallin suunnittelusyötteeksi.\n"
            "- Treenit ovat käyttäjäkohtaisia. Muut käyttäjät eivät pääse treeneihisi, ellei erillistä jakamista joskus lisätä.\n"
            "- /treenit poista poistaa yksittäisen treenin vahvistuksen jälkeen. Nimiä ja tageja voi muokata /treenit-komennoilla; sykerajoja /asetukset-komennoilla.\n"
            "- Laajempi käyttäjäkohtainen export/delete-komento ei ole vielä käytössä; toistaiseksi pyydä sitä ylläpitäjältä.\n"
            "- Kanavahistoria ja debug-jäljet ovat rajattuja operatiivisia tietoja. Treenit ja GPX:t säilyvät, kunnes poistat ne tai erillinen "
            "säilytyskäytäntö otetaan käyttöön."
        ),
        TranslationKey.HELP_UNKNOWN_TOPIC: (
            "Tuntematon help-aihe. Käytä: `yleinen`, `komennot`, `visualisointi`, `somekuva` tai `privacy`."
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
        TranslationKey.WORKOUT_RENAMED: "Nimesin treenin uudelleen: {title}.",
        TranslationKey.WORKOUT_TAG_ADDED: "Lisäsin tagin {tag} treenille: {title}.",
        TranslationKey.WORKOUT_TAG_REMOVED: "Poistin tagin {tag} treeniltä: {title}.",
        TranslationKey.WORKOUT_TAG_INVALID: "Tagin muoto ei kelpaa.",
        TranslationKey.SETTINGS_SUMMARY: "Asetuksesi:\n{settings}",
        TranslationKey.HR_ZONES_EMPTY: "Sinulle ei ole vielä asetettu sykerajoja.",
        TranslationKey.HR_ZONES_INVALID: (
            "Sykerajojen muoto ei kelpaa. Anna maksimisyke tai viisi nousevaa ylärajaa, "
            "esim. 190 tai 114,133,152,171,190."
        ),
        TranslationKey.HR_ZONES_SUMMARY: "Sykerajasi:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Päivitin sykerajat.",
        TranslationKey.GPX_ACCEPTED: "Tallensin GPX-tiedoston {filename} treeniksi: {title}.",
        TranslationKey.GPX_ACCEPTED_ROUTE: "Tallensin GPX-tiedoston {filename} reitiksi: {title}.",
        TranslationKey.GPX_DUPLICATE: "GPX-tiedosto {filename} on jo tallennettu treeniksi: {title}.",
        TranslationKey.GPX_DUPLICATE_ROUTE: "GPX-tiedosto {filename} on jo tallennettu reitiksi: {title}.",
        TranslationKey.GPX_REJECTED: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta: {filename}.",
        TranslationKey.VISUALIZATION_WORKING: "Työstän visualisointia...",
        TranslationKey.VISUALIZATION_CREATED: "Piirsin kuvaajan treenistä: {title}.",
        TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED: (
            "Kartalla voi korostaa vain yhtä data-arvoa kerrallaan. Valitsin ensimmäisen: {metric}."
        ),
        TranslationKey.OVERLAY_ANIMATION_CREATED: "Tein overlay-animaation treenistä: {title}.",
        TranslationKey.OVERLAY_ANIMATION_CREATED_LINK: (
            "Tein overlay-animaation treenistä: {title}.\n"
            "Tiedosto on liian iso Discord-liitteeksi, lataa se tästä: {url}"
        ),
        TranslationKey.OVERLAY_ANIMATION_BUNDLE_CREATED: 'Tein overlayt treenistä "{title}" {date}, alkaen {start_km} km:\n{items}',
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "Tuo liitetyyppi ei ole tuettu.",
        TranslationKey.ERROR_INVALID_GPX: "Tuo liite ei näytä kelvolliselta GPX-tiedostolta.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "En löytänyt pyynnölle sopivaa treeniä.",
        TranslationKey.ERROR_MISSING_METRIC: "Treenistä puuttuu tarvittava mittari: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "Löysin useamman mahdollisen treenin. Tarvitsen tarkemman viitteen.",
        TranslationKey.ERROR_NO_WORKOUTS_IN_PERIOD: "En löytänyt treenejä pyydetyltä jaksolta.",
        TranslationKey.ERROR_PERIOD_REQUEST_INVALID: "En saanut muodostettua kelvollista treenijakson rajausta.",
        TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID: "En saanut muodostettua kelvollista kuvaajasuunnitelmaa.",
        TranslationKey.ERROR_SOCIAL_IMAGE_REQUIRES_ROUTE: "Somekuva tarvitsee treenin, jossa on reittipisteet.",
        TranslationKey.ERROR_OVERLAY_ANIMATION_REQUIRES_ROUTE: "Overlay-animaatio tarvitsee treenin, jossa on reitti- ja matkapisteet.",
        TranslationKey.ERROR_OVERLAY_ANIMATION_ENCODER_UNAVAILABLE: "Overlay-videon enkooderi puuttuu. WebM-ulostulo vaatii ffmpeg-ohjelman tai imageio-ffmpeg-paketin.",
        TranslationKey.ERROR_RENDER_FAILED: "Kuvaajan piirtäminen epäonnistui.",
        TranslationKey.ERROR_MODEL_UNAVAILABLE: "Kielimalli ei ole juuri nyt käytettävissä.",
        TranslationKey.ERROR_PERMISSION_DENIED: "Sinulla ei ole oikeutta tähän toimintoon.",
        TranslationKey.ERROR_STORAGE_ERROR: "Tietojen tallennus tai haku epäonnistui.",
        TranslationKey.ERROR_UNEXPECTED: "Tapahtui odottamaton virhe.",
    },
    SupportedLanguage.EN: {
        TranslationKey.HELP_INTRO: (
            "**Aimo in brief**\n"
            "I can answer mentions, store GPX workouts, manage workouts, discuss training, and draw workout images.\n"
            "- Send a GPX attachment with a mention or `/gpx tallenna liite`.\n"
            "- Ask naturally: `@Aimo analyze my latest workout` or `@Aimo draw heart rate over time`.\n"
            "- Manage workouts with `/treenit` commands and settings with `/asetukset` commands.\n"
            "- Draw routes, period/trend charts, and social images with a mention.\n"
            "- I do not send raw GPX data or full point arrays to the language model.\n"
            "**Help topics:** `yleinen`, `komennot`, `visualisointi`, `somekuva`, `privacy`."
        ),
        TranslationKey.HELP_COMMANDS: (
            "**Commands**\n"
            "- `/aimo syote` asks, chats about workouts, or requests a chart in natural language.\n"
            "- `/gpx tallenna liite nimi` saves a GPX file; `nimi` is optional.\n"
            "- `/help aihe` shows help: `yleinen`, `komennot`, `visualisointi`, `somekuva`, `privacy`.\n"
            "- `/treenit listaa` lists workouts; `/treenit nayta viite` shows a workout and makes it current.\n"
            "- `/treenit aktiivinen` shows current workout; `/treenit aseta_aktiivinen viite` changes it.\n"
            "- `/treenit nimea viite nimi`, `tagaa viite tagi`, `poista_tagi viite tagi` edit a workout.\n"
            "- `/treenit poista viite` deletes only after a 60-second button confirmation.\n"
            "- `/asetukset nayta` shows settings; `/asetukset sykerajat zones` accepts e.g. `190` or `114,133,152,171,190`.\n"
            "- `/debug level` returns a bounded debug trace. On mentions, `+debug0`, `+debug1`, and `+debug2` add debug output to the response."
        ),
        TranslationKey.HELP_VISUALIZATION: (
            "**Visualizations**\n"
            "Ask with a mention: route map, line/time chart, bars, pie, period/trend chart, or social image.\n"
            "- Workout reference: latest, active, list number, date, date range, tag, sport/type, or search text.\n"
            "- Periods: this/last week, this/last month, last N days, all workouts, year to date.\n"
            "- Size: `+square`, `+portrait`, `+landscape`.\n"
            "- Metrics: `+hr`/`+syke`, `+elevation`/`+korkeus`, `+pace`/`+vauhti`, `+distance`/`+matka`, `+duration`/`+kesto`, `+ascent`/`+nousu`/`+nousumetrit`, `+maxhr`/`+maksimisyke`, `+date`/`+paiva`/`+päivä`.\n"
            "- A plustägi `+word` adds something, a miinustägi `-word` removes something, and a tarkenne `key=value` sets a value; e.g. `+hr`, `-waypoints`, `-korkeus`, `dim=45`.\n"
            "- Social image: `+social` or `+somekuva`; presets and tarkenteet: `/help aihe:somekuva`.\n"
            "- Overlay animation: `+overlay start=12.4km length=5s fps=10 size=1280x720 +map +speed +hr`; circular Resolve-compatible map: `+overlay +map dist=12.4km duration=60s transparent=true layout=circle_map map_style=dark tile_alpha=0.9`.\n"
            "- A route map can highlight one data metric at a time: `+hr`, `+elevation`, or `+pace`.\n"
            "- On single-route maps, GPX waypoints/route markers and kilometer markers are shown on the map; waypoints also appear in the overlay list. Hide waypoints with `-waypoints` or `-reittimerkit`.\n"
            "- On single-route maps, an elevation profile, grade colors, and kilometer axis are shown at the bottom when elevation data exists; hide them with `-elevation` or `-korkeus`.\n"
            "**Examples:** `@Aimo draw my latest workout route +hr`, `@Aimo show the route on a map -waypoints`, `@Aimo draw heart rate from active workout +portrait`."
        ),
        TranslationKey.HELP_SOCIAL_IMAGE: (
            "**Social images**\n"
            "Basic request: `@Aimo draw a social image from my latest workout +distance +duration +hr`. An attached image is used as background; otherwise a map is used.\n"
            "- Presets: `+classic`, `+minimal`, `+poster`, `+routeonly`, `+data`, `+photo`.\n"
            "- Size/stats: `+square`, `+portrait`, `+landscape`, `+distance`, `+duration`/`+kesto`, `+hr`, `+maxhr`, `+pace`, `+ascent`, `+date`.\n"
            "- A tarkenne is `key=value`, e.g. `dim=45 route=white title=bottom`; write it inline or on a `style:`/`tyyli:` line.\n"
            "- Background: `crop=center|top|bottom|left|right|X,Y`, `dim=0..70`, `blur=0..20`, `filter=none|warm|cool|bw|vivid|matte`.\n"
            "- Route: `route=default|auto|blue|white|black|red|green|yellow|#RRGGBB`, `route_size=small|normal|large|huge`, `route_shadow`/`markers`=`on|off|true|false|yes|no|1|0|kyllä|ei`, `route_pos=center|top|bottom|left|right`.\n"
            "- Text/data: `title=top|bottom|hide`, `title_align=left|center`, `stats=left|right|bottom|hide`, `stats_style=compact|large|stacked`, `panel=dark|light|none`, `text=white|black|#RRGGBB`, `accent=default|auto|blue|white|black|red|green|yellow|#RRGGBB`, `font=clean|bold|mono|serif`.\n"
            "- Aliases: `darken/tummennus=dim`, `shadow/varjo=route_shadow`, `reitti/route_color=route`, `data=stats`, `paneeli=panel`, `teksti=text`.\n"
            "**Examples:** `@Aimo draw a social image from my latest workout +poster +distance +hr style: route=white dim=25 title=bottom`, `@Aimo draw a social image from my latest workout +routeonly style: crop=50,35 filter=bw route_size=huge markers=off`."
        ),
        TranslationKey.HELP_PRIVACY: (
            "**Privacy and storage**\n"
            "- I store the user id, username/display name, bounded channel history, GPX attachment metadata and raw file, workout summaries, "
            "workout points, tags, active workout, heart-rate zones, rendered images, and redacted debug traces.\n"
            "- This data is used for conversation context, workout management, analysis, visualizations, and troubleshooting.\n"
            "- The language model receives only bounded context and summarized workout facts needed for the request; raw GPX data, full point arrays, "
            "image bytes, and secrets are not sent as model-planning input.\n"
            "- Workouts are user-owned. Other users cannot access your workouts unless explicit sharing is added later.\n"
            "- /treenit poista deletes one workout after confirmation. Names and tags can be edited with /treenit commands; heart-rate zones with /asetukset commands.\n"
            "- A broader per-user export/delete command is not available yet; ask an operator for now.\n"
            "- Channel history and debug traces are bounded operational data. Workouts and GPX files remain until you delete them or a separate "
            "retention policy is added."
        ),
        TranslationKey.HELP_UNKNOWN_TOPIC: "Unknown help topic. Use: `yleinen`, `komennot`, `visualisointi`, `somekuva`, or `privacy`.",
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
        TranslationKey.WORKOUT_RENAMED: "Renamed workout to: {title}.",
        TranslationKey.WORKOUT_TAG_ADDED: "Added tag {tag} to workout: {title}.",
        TranslationKey.WORKOUT_TAG_REMOVED: "Removed tag {tag} from workout: {title}.",
        TranslationKey.WORKOUT_TAG_INVALID: "The tag format is invalid.",
        TranslationKey.SETTINGS_SUMMARY: "Your settings:\n{settings}",
        TranslationKey.HR_ZONES_EMPTY: "You do not have heart-rate zones configured yet.",
        TranslationKey.HR_ZONES_INVALID: (
            "The heart-rate zone format is invalid. Provide max heart rate or five increasing upper limits, "
            "for example 190 or 114,133,152,171,190."
        ),
        TranslationKey.HR_ZONES_SUMMARY: "Your heart-rate zones:\n{zones}",
        TranslationKey.HR_ZONES_UPDATED: "Updated heart-rate zones.",
        TranslationKey.GPX_ACCEPTED: "Saved GPX file {filename} as workout: {title}.",
        TranslationKey.GPX_ACCEPTED_ROUTE: "Saved GPX file {filename} as route: {title}.",
        TranslationKey.GPX_DUPLICATE: "GPX file {filename} is already saved as workout: {title}.",
        TranslationKey.GPX_DUPLICATE_ROUTE: "GPX file {filename} is already saved as route: {title}.",
        TranslationKey.GPX_REJECTED: "That attachment does not look like a valid GPX file: {filename}.",
        TranslationKey.VISUALIZATION_WORKING: "Working on the visualization...",
        TranslationKey.VISUALIZATION_CREATED: "I drew the chart for workout: {title}.",
        TranslationKey.VISUALIZATION_ROUTE_COLOR_LIMITED: (
            "A route map can highlight only one data value at a time. I used the first one: {metric}."
        ),
        TranslationKey.OVERLAY_ANIMATION_CREATED: "I created an overlay animation for workout: {title}.",
        TranslationKey.OVERLAY_ANIMATION_CREATED_LINK: (
            "I created an overlay animation for workout: {title}.\n"
            "The file is too large for a Discord attachment, download it here: {url}"
        ),
        TranslationKey.OVERLAY_ANIMATION_BUNDLE_CREATED: 'I created overlays for "{title}" {date}, starting at {start_km} km:\n{items}',
        TranslationKey.ERROR_UNSUPPORTED_ATTACHMENT: "That attachment type is not supported.",
        TranslationKey.ERROR_INVALID_GPX: "That attachment does not look like a valid GPX file.",
        TranslationKey.ERROR_NO_MATCHING_WORKOUT: "I could not find a workout matching the request.",
        TranslationKey.ERROR_MISSING_METRIC: "The workout is missing a required metric: {metric}.",
        TranslationKey.ERROR_AMBIGUOUS_WORKOUT: "I found several possible workouts. I need a more specific reference.",
        TranslationKey.ERROR_NO_WORKOUTS_IN_PERIOD: "I did not find workouts in the requested period.",
        TranslationKey.ERROR_PERIOD_REQUEST_INVALID: "I could not build a valid workout-period selection.",
        TranslationKey.ERROR_VISUALIZATION_PLAN_INVALID: "I could not build a valid chart plan.",
        TranslationKey.ERROR_SOCIAL_IMAGE_REQUIRES_ROUTE: "A social image needs a workout with route points.",
        TranslationKey.ERROR_OVERLAY_ANIMATION_REQUIRES_ROUTE: "An overlay animation needs a workout with route and distance points.",
        TranslationKey.ERROR_OVERLAY_ANIMATION_ENCODER_UNAVAILABLE: "The overlay video encoder is unavailable. WebM output requires ffmpeg or the imageio-ffmpeg package.",
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
