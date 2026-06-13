from __future__ import annotations

import importlib
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from adapters.discord.commands import register_command_specs
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
        await self.client.start(token)

    async def sync_commands(self, *, guild: Any | None = None) -> None:
        tree = getattr(self.client, "tree", None)
        if tree is None:
            raise DiscordRuntimeError("Discord client does not expose a command tree")
        await register_command_specs(tree, guild=guild)


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

    @client.event
    async def on_ready() -> None:
        return None

    @client.event
    async def on_message(message: Any) -> None:
        bot_user_id = str(getattr(client.user, "id", ""))
        await handle_message(message, app_context, bot_user_id=bot_user_id, discord_module=module)

    return DiscordRuntime(client=client, app_context=app_context)


async def handle_message(
    message: Any,
    app_context: ApplicationContext,
    *,
    bot_user_id: str,
    discord_module: Any | None = None,
) -> None:
    if bool(getattr(getattr(message, "author", None), "bot", False)):
        return
    event = message_to_event(_message_snapshot(message), bot_user_id=bot_user_id)
    event = app_context.hydrate_attachments(event)
    result = app_context.dispatcher.dispatch(event, app_context.dispatch_context())
    for outgoing in (outgoing_to_discord(message, app_context.runtime.translator) for message in result.messages):
        await send_outbound(getattr(message, "channel"), outgoing, discord_module=discord_module)


async def handle_interaction(
    interaction: Any,
    app_context: ApplicationContext,
    *,
    discord_module: Any | None = None,
) -> None:
    event = slash_to_event(_slash_snapshot(interaction))
    if not _is_help_slash_event(event):
        event = app_context.hydrate_attachments(event)
    result = app_context.dispatcher.dispatch(event, app_context.dispatch_context())
    first = True
    for outgoing in (outgoing_to_discord(message, app_context.runtime.translator) for message in result.messages):
        responder = _interaction_responder(interaction, first=first)
        await send_outbound(responder, outgoing, discord_module=discord_module, ephemeral_supported=True)
        first = False


async def send_outbound(
    destination: Any,
    outbound: DiscordOutbound,
    *,
    discord_module: Any | None = None,
    ephemeral_supported: bool = False,
) -> None:
    kwargs: dict[str, Any] = {
        "content": outbound.text or None,
        "allowed_mentions": outbound.allowed_mentions,
    }
    if ephemeral_supported:
        kwargs["ephemeral"] = outbound.ephemeral
    if outbound.content is not None:
        module = discord_module or load_discord_module()
        kwargs["file"] = module.File(BytesIO(outbound.content), filename=outbound.filename or "aimo-output.bin")
    await destination.send(**kwargs)


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


def _is_help_slash_event(event: Any) -> bool:
    options = getattr(event, "metadata", {}).get("options", {})
    return isinstance(options, dict) and options.get("apua") is True


def _object_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "id", ""))


def _interaction_responder(interaction: Any, *, first: bool) -> Any:
    response = getattr(interaction, "response", None)
    if first and response is not None and not bool(getattr(response, "is_done", lambda: False)()):
        return _InteractionResponseSender(response)
    return getattr(interaction, "followup")


@dataclass(frozen=True)
class _InteractionResponseSender:
    response: Any

    async def send(self, **kwargs: Any) -> None:
        await self.response.send_message(**kwargs)
