from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from adapters.discord.commands import TREENIT_ACTIONS, command_specs_by_name, register_command_specs
from adapters.discord.normalization import (
    DiscordAttachmentSnapshot,
    DiscordMessageSnapshot,
    DiscordSlashSnapshot,
    DiscordUserSnapshot,
    message_to_event,
    slash_to_event,
)
from adapters.discord.outgoing import DiscordOutbound, outgoing_to_discord
from app.runtime import ApplicationContext
from core.i18n import TranslationKey


DiscordAttachment = Any
DiscordInteraction = Any
logger = logging.getLogger(__name__)


class DiscordRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiscordRuntime:
    client: Any
    app_context: ApplicationContext

    async def start(self) -> None:
        token = self.app_context.runtime.config.discord.token
        if not token:
            raise DiscordRuntimeError("Discord token is required")
        logger.info("Connecting Discord client.")
        await self.client.start(token)

    async def sync_commands(self, *, guild: Any | None = None) -> None:
        tree = getattr(self.client, "tree", None)
        if tree is None:
            raise DiscordRuntimeError("Discord client does not expose a command tree")
        logger.info("Synchronizing Discord slash commands.")
        await register_command_specs(tree, guild=guild)
        logger.info("Discord slash command synchronization finished.")


def load_discord_module() -> Any:
    try:
        return importlib.import_module("discord")
    except ImportError as exc:
        raise DiscordRuntimeError("discord.py is not installed") from exc


def build_discord_runtime(app_context: ApplicationContext, *, discord_module: Any | None = None) -> DiscordRuntime:
    module = discord_module or load_discord_module()
    intents = module.Intents.default()
    if hasattr(intents, "message_content"):
        intents.message_content = True
    client = module.Client(intents=intents)
    if hasattr(module, "app_commands"):
        client.tree = module.app_commands.CommandTree(client)
        _register_real_app_commands(client.tree, app_context, discord_module=module)

    @client.event
    async def on_ready() -> None:
        logger.info(
            "Aimo Discord runtime ready: user_id=%s guild_count=%s",
            getattr(getattr(client, "user", None), "id", ""),
            len(getattr(client, "guilds", ()) or ()),
        )
        return None

    @client.event
    async def on_message(message: Any) -> None:
        bot_user_id = str(getattr(client.user, "id", ""))
        try:
            await handle_message(message, app_context, bot_user_id=bot_user_id, discord_module=module)
        except Exception:
            logger.exception("Unhandled Discord message processing error.")

    if hasattr(module, "app_commands"):
        async def setup_hook() -> None:
            logger.info("Synchronizing Discord slash commands.")
            await client.tree.sync()
            logger.info("Discord slash command synchronization finished.")

        client.setup_hook = setup_hook

    return DiscordRuntime(client=client, app_context=app_context)


def _register_real_app_commands(command_tree: Any, app_context: ApplicationContext, *, discord_module: Any) -> None:
    app_commands = discord_module.app_commands
    specs = command_specs_by_name()
    globals()["DiscordAttachment"] = discord_module.Attachment
    globals()["DiscordInteraction"] = discord_module.Interaction

    @app_commands.command(name="aimo", description=specs["aimo"].description)
    @app_commands.describe(
        syote="Tekstipyyntö Aimolle.",
        liite="GPX-liite tallennettavaksi.",
    )
    async def aimo_command(
        interaction: DiscordInteraction,
        syote: str = "",
        liite: DiscordAttachment | None = None,
    ) -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @app_commands.command(name="treenit", description=specs["treenit"].description)
    @app_commands.describe(
        toiminto="Treenitoiminto.",
        viite="Treeni-id, listanumero, päivämäärä tai hakuteksti.",
        zones="Maksimisyke tai viisi ylärajaa, esim. 190 tai 114,133,152,171,190.",
    )
    @app_commands.choices(
        toiminto=[app_commands.Choice(name=action, value=action) for action in TREENIT_ACTIONS]
    )
    async def treenit_command(
        interaction: DiscordInteraction,
        toiminto: str,
        viite: str = "",
        zones: str = "",
    ) -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @app_commands.command(name="debug", description=specs["debug"].description)
    @app_commands.describe(tila="Debug-tila.")
    async def debug_command(interaction: DiscordInteraction, tila: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    command_tree.add_command(aimo_command)
    command_tree.add_command(treenit_command)
    command_tree.add_command(debug_command)


async def handle_message(
    message: Any,
    app_context: ApplicationContext,
    *,
    bot_user_id: str,
    discord_module: Any | None = None,
) -> None:
    if bool(getattr(getattr(message, "author", None), "bot", False)):
        return
    logger.info(
        "Discord message received: message_id=%s guild_id=%s channel_id=%s author_id=%s content_length=%s attachment_count=%s mention_count=%s",
        getattr(message, "id", ""),
        _object_id(getattr(message, "guild", None)),
        getattr(getattr(message, "channel", None), "id", ""),
        getattr(getattr(message, "author", None), "id", ""),
        len(str(getattr(message, "content", "") or "")),
        len(getattr(message, "attachments", ()) or ()),
        len(getattr(message, "mentions", ()) or ()),
    )
    event = message_to_event(_message_snapshot(message), bot_user_id=bot_user_id)
    logger.info(
        "Canonical message event: event_id=%s kind=%s mentioned_bot=%s text_length=%s",
        event.event_id,
        event.kind.value,
        event.metadata.get("mentioned_bot"),
        len(event.text),
    )
    event = app_context.hydrate_attachments(event)
    result = await asyncio.to_thread(app_context.dispatch_event_isolated, event)
    logger.info(
        "Discord message dispatch finished: event_id=%s status=%s outbound_count=%s",
        event.event_id,
        result.status.value,
        len(result.messages),
    )
    for outgoing in (outgoing_to_discord(message, app_context.runtime.translator) for message in result.messages):
        await send_outbound(getattr(message, "channel"), outgoing, discord_module=discord_module)


async def handle_interaction(
    interaction: Any,
    app_context: ApplicationContext,
    *,
    discord_module: Any | None = None,
) -> None:
    try:
        event = slash_to_event(_slash_snapshot(interaction))
        logger.info(
            "Discord interaction received: interaction_id=%s command=%s user_id=%s",
            event.event_id,
            event.metadata.get("command_name"),
            event.user_id,
        )
        await _defer_interaction(interaction)
        event = app_context.hydrate_attachments(event)
        result = await asyncio.to_thread(app_context.dispatch_event_isolated, event)
        logger.info(
            "Discord interaction dispatch finished: event_id=%s status=%s outbound_count=%s",
            event.event_id,
            result.status.value,
            len(result.messages),
        )
        first = True
        for outgoing in (outgoing_to_discord(message, app_context.runtime.translator) for message in result.messages):
            responder = _interaction_responder(interaction, first=first)
            await send_outbound(responder, outgoing, discord_module=discord_module, ephemeral_supported=True)
            first = False
    except Exception:
        logger.exception("Unhandled Discord interaction processing error.")
        await _send_interaction_error(interaction, app_context, discord_module=discord_module)


async def send_outbound(
    destination: Any,
    outbound: DiscordOutbound,
    *,
    discord_module: Any | None = None,
    ephemeral_supported: bool = False,
) -> None:
    kwargs: dict[str, Any] = {
        "content": outbound.text or None,
        "allowed_mentions": _allowed_mentions(outbound.allowed_mentions, discord_module=discord_module),
    }
    if ephemeral_supported:
        kwargs["ephemeral"] = outbound.ephemeral
    if outbound.content is not None:
        module = discord_module or load_discord_module()
        kwargs["file"] = module.File(BytesIO(outbound.content), filename=outbound.filename or "aimo-output.bin")
    await destination.send(**kwargs)


def _allowed_mentions(value: Any, *, discord_module: Any | None = None) -> Any:
    module = discord_module or load_discord_module()
    allowed_mentions = getattr(module, "AllowedMentions", None)
    if allowed_mentions is None:
        return value
    if hasattr(allowed_mentions, "none") and isinstance(value, dict) and value.get("parse") == []:
        return allowed_mentions.none()
    if hasattr(value, "to_dict"):
        return value
    if isinstance(value, dict):
        parse = set(value.get("parse", ()))
        return allowed_mentions(
            everyone="everyone" in parse,
            users="users" in parse,
            roles="roles" in parse,
        )
    return value


def _message_snapshot(message: Any) -> DiscordMessageSnapshot:
    return DiscordMessageSnapshot(
        message_id=str(message.id),
        guild_id=_object_id(getattr(message, "guild", None)),
        channel_id=str(getattr(getattr(message, "channel", None), "id", "")),
        author=_user_snapshot(message.author),
        content=str(getattr(message, "content", "")),
        created_at=getattr(message, "created_at"),
        attachments=tuple(_attachment_snapshot(attachment) for attachment in getattr(message, "attachments", ())),
        mentioned_user_ids=tuple(str(getattr(user, "id", "")) for user in getattr(message, "mentions", ())),
    )


def _slash_snapshot(interaction: Any) -> DiscordSlashSnapshot:
    command = getattr(interaction, "command", None)
    command_name = str(getattr(command, "name", "") or getattr(interaction, "command_name", ""))
    options = _interaction_options(interaction)
    return DiscordSlashSnapshot(
        interaction_id=str(interaction.id),
        guild_id=_object_id(getattr(interaction, "guild", None)),
        channel_id=str(getattr(getattr(interaction, "channel", None), "id", "")),
        user=_user_snapshot(interaction.user),
        command_name=command_name,
        options=options,
        created_at=getattr(interaction, "created_at"),
        attachments=tuple(_attachment_snapshot(attachment) for attachment in _interaction_attachments(interaction, options)),
    )


def _user_snapshot(user: Any) -> DiscordUserSnapshot:
    return DiscordUserSnapshot(
        user_id=str(getattr(user, "id", "")),
        user_name=str(getattr(user, "name", "")),
        display_name=str(getattr(user, "display_name", "")),
    )


def _attachment_snapshot(attachment: Any) -> DiscordAttachmentSnapshot:
    return DiscordAttachmentSnapshot(
        attachment_id=str(getattr(attachment, "id", "")),
        filename=str(getattr(attachment, "filename", "")),
        content_type=str(getattr(attachment, "content_type", "") or ""),
        size_bytes=getattr(attachment, "size", None),
        url=str(getattr(attachment, "url", "")),
    )


def _interaction_options(interaction: Any) -> dict[str, Any]:
    raw_options = getattr(interaction, "options", None)
    if isinstance(raw_options, dict):
        return dict(raw_options)
    namespace = getattr(interaction, "namespace", None)
    if namespace is not None:
        values = vars(namespace) if hasattr(namespace, "__dict__") else {}
        return {key: _option_value(value) for key, value in values.items() if not key.startswith("_")}
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return {
            str(option.get("name")): option.get("value")
            for option in data.get("options", ())
            if isinstance(option, dict) and option.get("name")
        }
    return {}


def _option_value(value: Any) -> Any:
    if hasattr(value, "id") and hasattr(value, "filename"):
        return str(getattr(value, "id"))
    return value


def _interaction_attachments(interaction: Any, options: dict[str, Any]) -> tuple[Any, ...]:
    direct = getattr(interaction, "attachments", None)
    if direct:
        return tuple(direct)
    namespace = getattr(interaction, "namespace", None)
    if namespace is not None:
        attachments = [
            value
            for value in vars(namespace).values()
            if hasattr(value, "filename") and hasattr(value, "url")
        ]
        if attachments:
            return tuple(attachments)
    resolved = getattr(interaction, "resolved", None)
    resolved_attachments = getattr(resolved, "attachments", None)
    if isinstance(resolved_attachments, dict):
        option_attachment_ids = {str(value) for value in options.values()}
        return tuple(
            attachment
            for attachment_id, attachment in resolved_attachments.items()
            if str(attachment_id) in option_attachment_ids
        )
    return ()


def _object_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "id", ""))


def _interaction_responder(interaction: Any, *, first: bool) -> Any:
    response = getattr(interaction, "response", None)
    if first and response is not None and not bool(getattr(response, "is_done", lambda: False)()):
        return _InteractionResponseSender(response)
    return getattr(interaction, "followup")


async def _send_interaction_error(
    interaction: Any,
    app_context: ApplicationContext,
    *,
    discord_module: Any | None = None,
) -> None:
    try:
        response = getattr(interaction, "response", None)
        first = response is not None and not bool(getattr(response, "is_done", lambda: False)())
        responder = _interaction_responder(interaction, first=first)
        await send_outbound(
            responder,
            DiscordOutbound(
                text=app_context.runtime.translator.text(TranslationKey.ERROR_UNEXPECTED),
                ephemeral=True,
            ),
            discord_module=discord_module,
            ephemeral_supported=True,
        )
    except Exception:
        logger.exception("Failed to send Discord interaction error response.")


async def _defer_interaction(interaction: Any) -> None:
    response = getattr(interaction, "response", None)
    if response is None or bool(getattr(response, "is_done", lambda: False)()):
        return
    defer = getattr(response, "defer", None)
    if defer is None:
        return
    await defer(thinking=True)


@dataclass(frozen=True)
class _InteractionResponseSender:
    response: Any

    async def send(self, **kwargs: Any) -> None:
        await self.response.send_message(**kwargs)
