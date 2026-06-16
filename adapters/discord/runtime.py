from __future__ import annotations

import asyncio
import importlib
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Awaitable, Callable

from adapters.discord.commands import command_specs_by_name, register_command_specs
from adapters.discord.normalization import (
    DiscordAttachmentSnapshot,
    DiscordComponentSnapshot,
    DiscordMessageSnapshot,
    DiscordSlashSnapshot,
    DiscordUserSnapshot,
    component_to_event,
    message_to_event,
    slash_to_event,
)
from adapters.discord.outgoing import DiscordOutbound, outgoing_to_discord
from app.runtime import ApplicationContext
from core.config import DiscordConfig
from core.i18n import TranslationKey


DiscordAttachment = Any
DiscordInteraction = Any
logger = logging.getLogger(__name__)
# Keep Discord callbacks alive longer than the workflow's business TTL so
# expired button presses can still return a controlled user-facing response.
COMPONENT_VIEW_TIMEOUT_SECONDS = 24 * 60 * 60
COMPONENT_DISABLE_AFTER_SECONDS = 60


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
        if guild is not None:
            await register_command_specs(tree, guild=guild)
            logger.info("Discord slash command synchronization finished.")
            return
        guilds = _allowed_guild_objects(self.app_context.runtime.config.discord, discord_module=None)
        if guilds:
            for allowed_guild in guilds:
                await register_command_specs(tree, guild=allowed_guild)
            logger.info("Discord slash command synchronization finished for %s guild(s).", len(guilds))
            return
        await register_command_specs(tree)
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
            await handle_message(
                message,
                app_context,
                bot_user_id=bot_user_id,
                discord_module=module,
                discord_client=client,
            )
        except Exception:
            logger.exception("Unhandled Discord message processing error.")

    if hasattr(module, "app_commands"):
        async def setup_hook() -> None:
            logger.info("Synchronizing Discord slash commands.")
            guilds = _allowed_guild_objects(app_context.runtime.config.discord, discord_module=module)
            if guilds:
                for guild in guilds:
                    await client.tree.sync(guild=guild)
                logger.info("Discord slash command synchronization finished for %s guild(s).", len(guilds))
            else:
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

    treenit_group = app_commands.Group(name="treenit", description=specs["treenit"].description)

    @treenit_group.command(name="listaa", description="Listaa tallennetut treenit.")
    async def treenit_listaa_command(interaction: DiscordInteraction) -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="nayta", description="Näytä treenin tiedot.")
    @app_commands.describe(viite="Treeni-id, listanumero, päivämäärä tai hakuteksti.")
    async def treenit_nayta_command(interaction: DiscordInteraction, viite: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="aktiivinen", description="Näytä aktiivinen treeni.")
    async def treenit_aktiivinen_command(interaction: DiscordInteraction) -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="aseta_aktiivinen", description="Aseta treeni aktiiviseksi.")
    @app_commands.describe(viite="Treeni-id, listanumero, päivämäärä tai hakuteksti.")
    async def treenit_aseta_aktiivinen_command(interaction: DiscordInteraction, viite: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="poista", description="Aloita treenin poisto.")
    @app_commands.describe(viite="Treeni-id, listanumero, päivämäärä tai hakuteksti.")
    async def treenit_poista_command(interaction: DiscordInteraction, viite: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="sykerajat", description="Näytä sykerajat.")
    async def treenit_sykerajat_command(interaction: DiscordInteraction) -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @treenit_group.command(name="aseta_sykerajat", description="Aseta sykerajat.")
    @app_commands.describe(zones="Maksimisyke tai viisi ylärajaa, esim. 190 tai 114,133,152,171,190.")
    async def treenit_aseta_sykerajat_command(interaction: DiscordInteraction, zones: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    @app_commands.command(name="debug", description=specs["debug"].description)
    @app_commands.describe(tila="Debug-tila.")
    async def debug_command(interaction: DiscordInteraction, tila: str = "") -> None:
        await handle_interaction(interaction, app_context, discord_module=discord_module)

    guilds = _allowed_guild_objects(app_context.runtime.config.discord, discord_module=discord_module)
    if guilds:
        for guild in guilds:
            command_tree.add_command(aimo_command, guild=guild)
            command_tree.add_command(treenit_group, guild=guild)
            command_tree.add_command(debug_command, guild=guild)
        return
    command_tree.add_command(aimo_command)
    command_tree.add_command(treenit_group)
    command_tree.add_command(debug_command)


async def handle_message(
    message: Any,
    app_context: ApplicationContext,
    *,
    bot_user_id: str,
    discord_module: Any | None = None,
    discord_client: Any | None = None,
) -> None:
    if bool(getattr(getattr(message, "author", None), "bot", False)):
        return
    snapshot = _message_snapshot(message)
    if not _discord_location_allowed(snapshot.guild_id, snapshot.channel_id, app_context.runtime.config.discord):
        logger.warning(
            "Discord message ignored from unauthorized location: message_id=%s guild_id=%s channel_id=%s",
            snapshot.message_id,
            snapshot.guild_id,
            snapshot.channel_id,
        )
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
    event = message_to_event(snapshot, bot_user_id=bot_user_id)
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
    await _send_first_interaction_admin_dm(
        result,
        app_context,
        discord_client=discord_client,
        discord_module=discord_module,
    )


async def handle_interaction(
    interaction: Any,
    app_context: ApplicationContext,
    *,
    discord_module: Any | None = None,
    discord_client: Any | None = None,
) -> None:
    try:
        is_component = _is_component_interaction(interaction)
        snapshot = _component_snapshot(interaction) if is_component else _slash_snapshot(interaction)
        if not _discord_location_allowed(snapshot.guild_id, snapshot.channel_id, app_context.runtime.config.discord):
            logger.warning(
                "Discord interaction rejected from unauthorized location: interaction_id=%s guild_id=%s channel_id=%s",
                snapshot.interaction_id,
                snapshot.guild_id,
                snapshot.channel_id,
            )
            await _send_interaction_permission_denied(interaction, app_context, discord_module=discord_module)
            return
        event = component_to_event(snapshot) if is_component else slash_to_event(snapshot)
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
            await send_outbound(
                responder,
                outgoing,
                discord_module=discord_module,
                ephemeral_supported=True,
                component_callback=lambda component_interaction: handle_interaction(
                    component_interaction,
                    app_context,
                    discord_module=discord_module,
                    discord_client=discord_client or getattr(interaction, "client", None),
                ),
            )
            first = False
        await _send_first_interaction_admin_dm(
            result,
            app_context,
            discord_client=discord_client or getattr(interaction, "client", None),
            discord_module=discord_module,
        )
    except Exception:
        logger.exception("Unhandled Discord interaction processing error.")
        await _send_interaction_error(interaction, app_context, discord_module=discord_module)


async def send_outbound(
    destination: Any,
    outbound: DiscordOutbound,
    *,
    discord_module: Any | None = None,
    ephemeral_supported: bool = False,
    component_callback: Callable[[Any], Awaitable[None]] | None = None,
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
    view = _discord_view(outbound, discord_module=discord_module, component_callback=component_callback)
    if view is not None:
        kwargs["view"] = view
    message = await _send_destination(destination, kwargs, wait_for_message=view is not None)
    if view is not None and message is not None:
        _schedule_component_disable(message, view, delay_seconds=COMPONENT_DISABLE_AFTER_SECONDS)


def _discord_view(
    outbound: DiscordOutbound,
    *,
    discord_module: Any | None = None,
    component_callback: Callable[[Any], Awaitable[None]] | None = None,
) -> Any | None:
    if not outbound.components:
        return None
    module = discord_module or load_discord_module()
    ui = getattr(module, "ui", None)
    button_style = getattr(module, "ButtonStyle", None)
    if ui is None or button_style is None:
        return None
    view = ui.View(timeout=COMPONENT_VIEW_TIMEOUT_SECONDS)
    for component in outbound.components:
        button = ui.Button(
            label=component.label,
            style=_button_style(component.style, button_style),
            custom_id=component.component_id,
        )
        if component_callback is not None:
            button.callback = _component_callback(component_callback, view)
        view.add_item(button)
    return view


async def _send_destination(destination: Any, kwargs: dict[str, Any], *, wait_for_message: bool) -> Any | None:
    if wait_for_message and not isinstance(destination, _InteractionResponseSender):
        try:
            return await destination.send(**kwargs, wait=True)
        except TypeError:
            pass
    return await destination.send(**kwargs)


def _component_callback(callback: Callable[[Any], Awaitable[None]], view: Any) -> Callable[[Any], Awaitable[None]]:
    async def wrapped(interaction: Any) -> None:
        await callback(interaction)
        await _disable_interaction_message(interaction, view)

    return wrapped


def _schedule_component_disable(message: Any, view: Any, *, delay_seconds: int) -> None:
    try:
        asyncio.get_running_loop().create_task(_disable_component_message_after(message, view, delay_seconds=delay_seconds))
    except RuntimeError:
        logger.debug("Could not schedule component disable outside a running event loop.")


async def _disable_component_message_after(message: Any, view: Any, *, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    await _disable_message_components(message, view)


async def _disable_interaction_message(interaction: Any, view: Any) -> None:
    message = getattr(interaction, "message", None)
    if message is None:
        return
    await _disable_message_components(message, view)


async def _disable_message_components(message: Any, view: Any) -> None:
    if _view_components_disabled(view):
        return
    _set_view_components_disabled(view)
    edit = getattr(message, "edit", None)
    if edit is None:
        return
    try:
        await edit(view=view)
    except Exception:
        logger.exception("Failed to disable Discord message components.")


def _set_view_components_disabled(view: Any) -> None:
    for item in _view_items(view):
        if hasattr(item, "disabled"):
            item.disabled = True


def _view_components_disabled(view: Any) -> bool:
    items = _view_items(view)
    return bool(items) and all(bool(getattr(item, "disabled", False)) for item in items)


def _view_items(view: Any) -> tuple[Any, ...]:
    children = getattr(view, "children", None)
    if children is not None:
        return tuple(children)
    return tuple(getattr(view, "items", ()) or ())


def _button_style(style: str, button_style: Any) -> Any:
    normalized = style.strip().lower()
    if normalized == "danger" and hasattr(button_style, "danger"):
        return button_style.danger
    if normalized == "primary" and hasattr(button_style, "primary"):
        return button_style.primary
    if normalized == "success" and hasattr(button_style, "success"):
        return button_style.success
    return getattr(button_style, "secondary", None)


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


def _discord_location_allowed(guild_id: str | None, channel_id: str, config: DiscordConfig) -> bool:
    if guild_id is None:
        return False
    if config.allowed_guild_ids and guild_id not in config.allowed_guild_ids:
        return False
    if config.allowed_channel_ids and channel_id not in config.allowed_channel_ids:
        return False
    return True


def _allowed_guild_objects(config: DiscordConfig, *, discord_module: Any | None) -> tuple[Any, ...]:
    if not config.allowed_guild_ids:
        return ()
    module = discord_module
    guilds: list[Any] = []
    for guild_id in sorted(config.allowed_guild_ids):
        if module is not None and hasattr(module, "Object"):
            try:
                guilds.append(module.Object(id=int(guild_id)))
                continue
            except ValueError:
                logger.warning("Skipping non-numeric Discord guild id for command sync: %s", guild_id)
                continue
        guilds.append(guild_id)
    return tuple(guilds)


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
    command_name = _command_name(interaction, command)
    subcommand, options = _interaction_subcommand_and_options(interaction, command)
    return DiscordSlashSnapshot(
        interaction_id=str(interaction.id),
        guild_id=_object_id(getattr(interaction, "guild", None)),
        channel_id=str(getattr(getattr(interaction, "channel", None), "id", "")),
        user=_user_snapshot(interaction.user),
        command_name=command_name,
        subcommand=subcommand,
        options=options,
        created_at=getattr(interaction, "created_at"),
        attachments=tuple(_attachment_snapshot(attachment) for attachment in _interaction_attachments(interaction, options)),
    )


def _component_snapshot(interaction: Any) -> DiscordComponentSnapshot:
    component_id = _component_id(interaction)
    command_name, subcommand, pending_id = _parse_component_id(component_id)
    return DiscordComponentSnapshot(
        interaction_id=str(interaction.id),
        guild_id=_object_id(getattr(interaction, "guild", None)),
        channel_id=str(getattr(getattr(interaction, "channel", None), "id", "")),
        user=_user_snapshot(interaction.user),
        component_id=component_id,
        command_name=command_name,
        subcommand=subcommand,
        pending_id=pending_id,
        created_at=getattr(interaction, "created_at"),
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


def _interaction_subcommand_and_options(interaction: Any, command: Any) -> tuple[str, dict[str, Any]]:
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        raw_options = data.get("options", ())
        if raw_options:
            first = raw_options[0]
            if isinstance(first, dict) and first.get("name") and first.get("type") in {1, "subcommand"}:
                return str(first.get("name")), _option_dict(first.get("options", ()))
    subcommand = _subcommand_name(command)
    return subcommand, _interaction_options(interaction)


def _option_dict(raw_options: Any) -> dict[str, Any]:
    return {
        str(option.get("name")): option.get("value")
        for option in raw_options or ()
        if isinstance(option, dict) and option.get("name")
    }


def _command_name(interaction: Any, command: Any) -> str:
    parent = getattr(command, "parent", None)
    parent_name = str(getattr(parent, "name", "") or "")
    if parent_name:
        return parent_name
    data = getattr(interaction, "data", None)
    if isinstance(data, dict) and data.get("name"):
        return str(data.get("name"))
    return str(getattr(command, "name", "") or getattr(interaction, "command_name", ""))


def _subcommand_name(command: Any) -> str:
    parent = getattr(command, "parent", None)
    if parent is not None:
        return str(getattr(command, "name", "") or "")
    return ""


def _is_component_interaction(interaction: Any) -> bool:
    return bool(_component_id(interaction))


def _component_id(interaction: Any) -> str:
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        custom_id = data.get("custom_id")
        if custom_id:
            return str(custom_id)
    return str(getattr(interaction, "custom_id", "") or "")


def _parse_component_id(component_id: str) -> tuple[str, str, str]:
    parts = component_id.split(":", 2)
    if len(parts) != 3:
        return "", "", ""
    command_name, subcommand, pending_id = parts
    return command_name, subcommand, pending_id


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


async def _send_interaction_permission_denied(
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
                text=app_context.runtime.translator.text(TranslationKey.ERROR_PERMISSION_DENIED),
                ephemeral=True,
            ),
            discord_module=discord_module,
            ephemeral_supported=True,
        )
    except Exception:
        logger.exception("Failed to send Discord interaction permission response.")


async def _send_first_interaction_admin_dm(
    result: Any,
    app_context: ApplicationContext,
    *,
    discord_client: Any | None,
    discord_module: Any | None = None,
) -> None:
    if discord_client is None:
        return
    admin_user_ids = app_context.runtime.config.admin.user_ids
    if not admin_user_ids:
        return
    for update in getattr(result, "state_updates", ()) or ():
        if getattr(update, "namespace", "") != "users" or getattr(update, "operation", "") != "first_interaction":
            continue
        payload = getattr(update, "payload", {}) or {}
        text = _first_interaction_admin_text(payload)
        for admin_user_id in sorted(admin_user_ids):
            try:
                admin_user = await _fetch_discord_user(discord_client, admin_user_id)
                if admin_user is None:
                    logger.warning("Could not fetch admin user for first interaction DM: admin_user_id=%s", admin_user_id)
                    continue
                await send_outbound(
                    admin_user,
                    DiscordOutbound(text=text),
                    discord_module=discord_module,
                )
            except Exception:
                logger.exception("Failed to send first interaction admin DM: admin_user_id=%s", admin_user_id)


async def _fetch_discord_user(discord_client: Any, user_id: str) -> Any | None:
    get_user = getattr(discord_client, "get_user", None)
    if get_user is not None:
        try:
            cached = get_user(int(user_id))
        except ValueError:
            cached = get_user(user_id)
        if cached is not None:
            return cached
    fetch_user = getattr(discord_client, "fetch_user", None)
    if fetch_user is None:
        return None
    try:
        return await fetch_user(int(user_id))
    except ValueError:
        return await fetch_user(user_id)


def _first_interaction_admin_text(payload: dict[str, Any]) -> str:
    display_name = str(payload.get("discord_display_name", "") or "")
    user_name = str(payload.get("user_name", "") or "")
    user_label = display_name or user_name or "(unknown)"
    command_name = str(payload.get("command_name", "") or "")
    command_part = f"\nCommand: /{command_name}" if command_name else ""
    return (
        "Aimo first user interaction\n"
        f"User: {user_label} ({payload.get('user_id', '')})\n"
        f"Kind: {payload.get('interaction_kind', '')}\n"
        f"Guild: {payload.get('guild_id', '')}\n"
        f"Channel: {payload.get('channel_id', '')}\n"
        f"Event: {payload.get('event_id', '')}\n"
        f"At: {payload.get('created_at', '')}"
        f"{command_part}"
    )


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
