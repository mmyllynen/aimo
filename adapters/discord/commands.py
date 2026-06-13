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


TREENIT_ACTIONS = (
    "listaa",
    "nayta",
    "aktiivinen",
    "aseta_aktiivinen",
    "poista",
    "sykerajat",
    "aseta_sykerajat",
)


COMMAND_SPECS = (
    DiscordCommandSpec(
        name="aimo",
        description="Aimo yleiskomento: apu, GPX-liite tai tekstipyyntö.",
        options=(
            DiscordCommandOptionSpec(
                name="apua",
                description="Näytä Aimon käyttöohje.",
                option_type=DiscordCommandOptionType.BOOLEAN,
            ),
            DiscordCommandOptionSpec(
                name="syote",
                description="Tekstipyyntö Aimolle.",
                option_type=DiscordCommandOptionType.STRING,
            ),
            DiscordCommandOptionSpec(
                name="liite",
                description="GPX-liite tallennettavaksi.",
                option_type=DiscordCommandOptionType.ATTACHMENT,
            ),
        ),
    ),
    DiscordCommandSpec(
        name="treenit",
        description="Listaa, näytä ja hallitse tallennettuja treenejä.",
        options=(
            DiscordCommandOptionSpec(
                name="toiminto",
                description="Treenitoiminto.",
                option_type=DiscordCommandOptionType.STRING,
                required=True,
                choices=TREENIT_ACTIONS,
            ),
            DiscordCommandOptionSpec(
                name="viite",
                description="Treeni-id, listanumero, päivämäärä tai hakuteksti.",
                option_type=DiscordCommandOptionType.STRING,
            ),
            DiscordCommandOptionSpec(
                name="zones",
                description="JSON-lista sykerajoista.",
                option_type=DiscordCommandOptionType.STRING,
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
        "options": [
            {
                "name": option.name,
                "description": option.description,
                "type": option.option_type.value,
                "required": option.required,
                "choices": list(option.choices),
            }
            for option in spec.options
        ],
    }
