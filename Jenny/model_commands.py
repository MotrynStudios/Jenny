"""Dispatch model-selected commands through the registered Discord callbacks."""

import inspect
import json
import re

import discord
from discord import app_commands

from discord_commands import DM_COMMANDS, send_more_from_cache
from database import log_message
import asyncio


def parse_model_command(reply):
    """Only a leading control header can invoke a command."""
    match = re.match(r"^\s*CMD\s*:\s*(\w+)(.*)$", reply, re.I | re.S)
    return (match[1].lower(), match[2].strip()) if match else None


def contains_control_text(text):
    return bool(re.search(
        r"\bCMD\s*:|^\s*(?:NO_RESPONSE|NEED_SEARCH|KILLTTS|JOIN_VC|LEAVE_VC|REPLY_MODE_\w+)\b",
        text or "", re.I,
    ))


def command_allowed(command, actor, guild):
    if not guild:
        return command.name in DM_COMMANDS
    required = command.default_permissions
    return not required or actor.guild_permissions.is_superset(required)


def command_catalog(bot, actor, guild):
    lines = []
    for command in bot.tree.get_commands():
        if not isinstance(command, app_commands.Command) or not command_allowed(command, actor, guild):
            continue
        args = []
        for parameter in command.parameters:
            choices = "/".join(str(choice.value) for choice in parameter.choices)
            kind = choices or parameter.type.name
            args.append(f"{parameter.name}:{kind}{'' if parameter.required else '?'}")
        lines.append(f"{command.name} {' '.join(args)} | {command.description}")
    return (
        "Available command names and arguments (? means optional). For your own usage select myusage. "
        "Use the exact current member name, mention or ID for member arguments; use 'me' for the requester. "
        "For 'my roles' pass user='me' to roles. Without a user, roles lists the server's roles. "
        "Use next_result only when asked to advance an existing saved paged result or solo trivia. "
        "A new trivia request uses trivia; specify category only if asked, and mode solo in DMs.\n"
        + "\n".join(lines)
    )


def describe_discord_message(message, limit=2800):
    """Capture the visible content of the exact message, including embed-only replies."""
    parts = [message.content] if message.content else []
    for embed in message.embeds[:4]:
        for value in (embed.title, embed.description):
            if value:
                parts.append(value)
        parts.extend(f"{field.name}: {field.value}" for field in embed.fields[:10])
        if embed.footer.text:
            parts.append(embed.footer.text)
    parts.extend(f"Attachment: {attachment.filename}" for attachment in message.attachments[:4])
    return "\n".join(parts)[:limit]


class ModelCommandContext:
    """Message-backed response surface shared by chat, DMs and voice."""

    def __init__(self, user, channel, source=None):
        self.user, self.channel, self.source = user, channel, source
        self.guild = getattr(channel, "guild", None)
        self.guild_id = self.guild.id if self.guild else None
        self.channel_id = channel.id
        self.response = self.followup = self
        self.command = None
        self.message = None  # Slash callbacks distinguish an initial send from a component update.
        self.sent = None
        self.result = ""
        self.failed = False
        self.private = False
        self.deferred = False

    def is_done(self):
        return self.deferred or self.sent is not None

    async def defer(self, **kwargs):
        self.deferred = True

    async def send(self, content=None, *, ephemeral=False, wait=False, **kwargs):
        sender = self.source.reply if self.source else self.channel.send
        if self.source:
            kwargs["mention_author"] = False
        kwargs.setdefault("allowed_mentions", discord.AllowedMentions.none())
        if ephemeral and self.guild:
            kwargs.pop("mention_author", None)
            sender = self.user.send
            self.private = True
        sent = await sender(content, **kwargs)
        self.sent = self.sent or sent
        self.result = "Sent a private report." if self.private else describe_discord_message(sent, 900)
        return sent

    send_message = send

    async def reply(self, content=None, **kwargs):
        kwargs.pop("mention_author", None)
        return await self.send(content, **kwargs)

    @property
    def author(self):
        return self.user

    @property
    def id(self):
        return self.source.id if self.source else self.channel_id

    async def original_response(self):
        return self.sent

    async def edit_original_response(self, **kwargs):
        if self.sent is None:
            return await self.send(**kwargs)
        edited = await self.sent.edit(**kwargs)
        self.result = describe_discord_message(edited, 900)
        return edited


def _resolve_argument(parameter, value, context):
    name, kind = parameter.name, parameter.type
    if kind in (discord.AppCommandOptionType.user, discord.AppCommandOptionType.role):
        if not context.guild or not isinstance(value, (str, int)) or isinstance(value, bool):
            raise ValueError(f"Specify a server {kind.name} for {name}.")
        is_user = kind == discord.AppCommandOptionType.user
        query = str(value).strip()
        if is_user and query.casefold() in {"me", "myself"}:
            return context.user
        if is_user and query.casefold() == "jenny" and context.guild.me:
            return context.guild.me
        match = re.fullmatch(r"(?:<@(?:!|&)?)?(\d+)>?", query)
        pool = context.guild.members if is_user else context.guild.roles
        if match:
            result = (context.guild.get_member if is_user else context.guild.get_role)(int(match[1]))
            if result:
                return result
            raise ValueError(f"No server {kind.name} matches that ID.")
        query = query.lstrip("@").casefold()
        matches = [item for item in pool if query in {
            item.name.casefold(), str(getattr(item, "display_name", "")).casefold(),
            str(getattr(item, "global_name", "") or "").casefold(),
        }]
        if len(matches) != 1:
            options = ", ".join(f"{item.name} ({item.id})" for item in matches[:5])
            raise ValueError(f"Which {kind.name} did you mean by {value!s}?" + (f" Matches: {options}." if options else " No exact match."))
        return matches[0]
    if kind == discord.AppCommandOptionType.integer and type(value) is not int:
        raise ValueError(f"{name} must be a whole number.")
    if kind == discord.AppCommandOptionType.string and not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    if parameter.choices and value not in {choice.value for choice in parameter.choices}:
        raise ValueError(f"Choose a valid value for {name}.")
    if ((parameter.min_value is not None and value < parameter.min_value)
            or (parameter.max_value is not None and value > parameter.max_value)):
        raise ValueError(f"{name} must be between {parameter.min_value} and {parameter.max_value}.")
    return value


async def execute_model_command(bot, context, command_name, payload):
    """Validate the model's selection, then run the same handler as the slash command."""
    try:
        args, acknowledgement = {}, ""
        if payload.startswith("{"):
            args, offset = json.JSONDecoder().raw_decode(payload)
            acknowledgement = payload[offset:].strip()
            if not isinstance(args, dict):
                raise ValueError("Command arguments must be a JSON object.")
        elif payload:
            # Older model prompts used positional trivia options.
            old = re.fullmatch(r"(solo|party) (easy|medium|hard) (\d+)", payload, re.I)
            if command_name == "trivia" and old:
                args = {"mode": old[1].lower(), "difficulty": old[2].lower(), "rounds": int(old[3])}
            else:
                acknowledgement = payload
        if contains_control_text(acknowledgement):
            acknowledgement = ""
        if command_name == "next_result":
            scope = (f"guild:{context.guild_id}:channel:{context.channel_id}" if context.guild
                     else f"dm:{context.user.id}")
            reference = context.source.reference if context.source else None
            target = str(reference.message_id) if reference and reference.message_id else None
            if not await send_more_from_cache(context, str(context.user.id), context.guild_id, scope, target):
                raise ValueError("There is no recent result to continue here.")
        else:
            command = bot.tree.get_command(command_name)
            if not isinstance(command, app_commands.Command) or not command_allowed(command, context.user, context.guild):
                raise ValueError("That command is unavailable here or requires additional permissions.")
            context.command = command
            for check in command.checks:
                passed = check(context)
                if inspect.isawaitable(passed):
                    passed = await passed
                if not passed:
                    raise ValueError("You do not have permission to run that command here.")
            parameters = {parameter.name: parameter for parameter in command.parameters}
            if args.keys() - parameters.keys():
                raise ValueError("I couldn't match the requested command options.")
            for name, parameter in parameters.items():
                if parameter.required and name not in args:
                    raise ValueError(f"I still need {name} for /{command_name}.")
            resolved = {name: _resolve_argument(parameters[name], value, context) for name, value in args.items()}
            print(f"[COMMAND] Model selected /{command_name} for {context.user.id} in {context.channel_id}")
            try:
                await asyncio.to_thread(log_message, "Jenny (System)",
                                        f"[Command] {context.user.display_name} requested /{command_name}.",
                                        context.user.id, context.channel_id, context.guild_id)
            except Exception as error:
                print(f"[CONTEXT] Could not record command activity: {error}")
            await command.callback(context, **resolved)
        return context.result, acknowledgement
    except Exception as error:
        context.failed = True
        print(f"[COMMAND] /{command_name} failed: {type(error).__name__}: {error}")
        detail = str(error)[:1000] if isinstance(error, ValueError) else "I couldn't finish that command."
        await context.send(embed=discord.Embed(title="Command unavailable", description=detail, color=discord.Color.red()))
        return context.result, ""
