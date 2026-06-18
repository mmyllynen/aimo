from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DiscordCommandOptionType(StrEnum):
    STRING = "string"
    BOOLEAN = "boolean"
    ATTACHMENT = "attachment"


@dataclass(frozen=True)
class DiscordCommandOptionSpec:
    name: str
    description: str
    option_type: DiscordCommandOptionType
    required: bool = False
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscordCommandSpec:
    name: str
    description: str
    options: tuple[DiscordCommandOptionSpec, ...] = ()
    subcommands: tuple["DiscordSubcommandSpec", ...] = ()


@dataclass(frozen=True)
class DiscordSubcommandSpec:
    name: str
    description: str
    options: tuple[DiscordCommandOptionSpec, ...] = ()


WORKOUT_REFERENCE_OPTION = DiscordCommandOptionSpec(
    name="viite",
    description="Treeni-id, listanumero, päivämäärä tai hakuteksti.",
    option_type=DiscordCommandOptionType.STRING,
)

HEART_RATE_ZONES_OPTION = DiscordCommandOptionSpec(
    name="zones",
    description="Maksimisyke tai viisi ylärajaa, esim. 190 tai 114,133,152,171,190.",
    option_type=DiscordCommandOptionType.STRING,
    required=True,
)

GPX_ATTACHMENT_OPTION = DiscordCommandOptionSpec(
    name="liite",
    description="GPX-liite tallennettavaksi.",
    option_type=DiscordCommandOptionType.ATTACHMENT,
    required=True,
)

REQUIRED_WORKOUT_TITLE_OPTION = DiscordCommandOptionSpec(
    name="nimi",
    description="Uusi treenin nimi.",
    option_type=DiscordCommandOptionType.STRING,
    required=True,
)

OPTIONAL_WORKOUT_TITLE_OPTION = DiscordCommandOptionSpec(
    name="nimi",
    description="Treenille annettava nimi.",
    option_type=DiscordCommandOptionType.STRING,
)

WORKOUT_TAG_OPTION = DiscordCommandOptionSpec(
    name="tagi",
    description="Lisättävä tai poistettava tagi.",
    option_type=DiscordCommandOptionType.STRING,
    required=True,
)

HELP_TOPIC_OPTION = DiscordCommandOptionSpec(
    name="aihe",
    description="Help-aihe: yleinen, komennot, visualisointi, somekuva tai privacy.",
    option_type=DiscordCommandOptionType.STRING,
    choices=("yleinen", "komennot", "visualisointi", "somekuva", "privacy"),
)


COMMAND_SPECS = (
    DiscordCommandSpec(
        name="aimo",
        description="Aimo-chat ja luonnollisen kielen pyynnöt.",
        options=(
            DiscordCommandOptionSpec(
                name="syote",
                description="Tekstipyyntö Aimolle.",
                option_type=DiscordCommandOptionType.STRING,
            ),
        ),
    ),
    DiscordCommandSpec(
        name="gpx",
        description="Tallenna GPX-liitteitä treeneiksi.",
        subcommands=(
            DiscordSubcommandSpec(
                name="tallenna",
                description="Tallenna GPX-liite treeniksi.",
                options=(GPX_ATTACHMENT_OPTION, OPTIONAL_WORKOUT_TITLE_OPTION),
            ),
        ),
    ),
    DiscordCommandSpec(
        name="help",
        description="Näytä Aimon käyttö-, komento- tai tietosuojainfo.",
        options=(HELP_TOPIC_OPTION,),
    ),
    DiscordCommandSpec(
        name="treenit",
        description="Listaa, näytä ja hallitse tallennettuja treenejä.",
        subcommands=(
            DiscordSubcommandSpec(name="listaa", description="Listaa tallennetut treenit."),
            DiscordSubcommandSpec(name="nayta", description="Näytä treenin tiedot.", options=(WORKOUT_REFERENCE_OPTION,)),
            DiscordSubcommandSpec(name="aktiivinen", description="Näytä aktiivinen treeni."),
            DiscordSubcommandSpec(
                name="aseta_aktiivinen",
                description="Aseta treeni aktiiviseksi.",
                options=(WORKOUT_REFERENCE_OPTION,),
            ),
            DiscordSubcommandSpec(name="poista", description="Aloita treenin poisto.", options=(WORKOUT_REFERENCE_OPTION,)),
            DiscordSubcommandSpec(
                name="nimea",
                description="Nimeä treeni uudelleen.",
                options=(WORKOUT_REFERENCE_OPTION, REQUIRED_WORKOUT_TITLE_OPTION),
            ),
            DiscordSubcommandSpec(
                name="tagaa",
                description="Lisää treenille tagi.",
                options=(WORKOUT_REFERENCE_OPTION, WORKOUT_TAG_OPTION),
            ),
            DiscordSubcommandSpec(
                name="poista_tagi",
                description="Poista treeniltä tagi.",
                options=(WORKOUT_REFERENCE_OPTION, WORKOUT_TAG_OPTION),
            ),
        ),
    ),
    DiscordCommandSpec(
        name="asetukset",
        description="Näytä ja muuta käyttäjäkohtaisia asetuksia.",
        subcommands=(
            DiscordSubcommandSpec(name="nayta", description="Näytä asetukset."),
            DiscordSubcommandSpec(
                name="sykerajat",
                description="Aseta sykerajat.",
                options=(HEART_RATE_ZONES_OPTION,),
            ),
        ),
    ),
    DiscordCommandSpec(
        name="debug",
        description="Palauta viimeisin rajattu debug-jälki.",
        options=(
            DiscordCommandOptionSpec(
                name="tila",
                description="Debug-tila.",
                option_type=DiscordCommandOptionType.STRING,
            ),
        ),
    ),
)


def command_specs_by_name() -> dict[str, DiscordCommandSpec]:
    return {spec.name: spec for spec in COMMAND_SPECS}


async def register_command_specs(command_tree: Any, *, guild: Any | None = None) -> None:
    for spec in COMMAND_SPECS:
        if hasattr(command_tree, "add_command_spec"):
            command_tree.add_command_spec(spec, guild=guild)
        else:
            command_tree.add_command(_to_mapping(spec), guild=guild)
    result = command_tree.sync(guild=guild)
    if hasattr(result, "__await__"):
        await result


def _to_mapping(spec: DiscordCommandSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "options": [_option_mapping(option) for option in spec.options]
        + [
            {
                "name": subcommand.name,
                "description": subcommand.description,
                "type": "subcommand",
                "options": [_option_mapping(option) for option in subcommand.options],
            }
            for subcommand in spec.subcommands
        ],
    }


def _option_mapping(option: DiscordCommandOptionSpec) -> dict[str, Any]:
    return {
        "name": option.name,
        "description": option.description,
        "type": option.option_type.value,
        "required": option.required,
        "choices": list(option.choices),
    }
