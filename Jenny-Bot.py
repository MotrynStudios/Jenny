import os
import re

import discord
from discord.ext import commands
from dotenv import load_dotenv

from ai import generate, generate_vision
from database import (
    log_message,
    get_recent_log_text,
    get_user_history,
    save_user_history,
    get_main_channel_id,
)
from discord_commands import setup_commands

from Prompts import SYSTEM_PROMPT

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

MAX_HISTORY_PER_USER = 12
GLOBAL_LOG_CONTEXT_HOURS = 24
MESSAGE_SEARCH_LIMIT = 3000

STOPWORDS = {
    "jenny", "when", "was", "is", "did", "does", "anyone", "someone", "can",
    "you", "see", "check", "last", "online", "active", "seen", "message",
    "messaged", "talked", "spoke", "time", "the", "a", "an", "in", "on",
    "at", "were", "has", "have", "had", "who", "what", "for",
}

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Setup commands from discord_commands.py
setup_commands(bot)


def guess_target_name(text):
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [
        word
        for word in words
        if word not in STOPWORDS and len(word) >= 3
    ]


async def search_last_message(channel, name_query):
    try:
        async for msg in channel.history(limit=MESSAGE_SEARCH_LIMIT):
            if name_query in msg.author.display_name.lower():
                return msg
    except Exception as e:
        print(f"Error searching messages: {e}")
    return None


@bot.event
async def on_ready():
    print(f"=== BOT STARTED ===")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Process ID: {os.getpid()}")
    print("Jenny is online and ready!")
    
    main_channel_id = get_main_channel_id()
    if main_channel_id:
        print(f"Main channel set to: {main_channel_id}")
    else:
        print("No main channel configured. Use !setmainchannel in the desired channel.")
    print(f"==================")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    main_channel_id = get_main_channel_id()
    is_main_channel = main_channel_id and str(message.channel.id) == main_channel_id
    is_admin = message.author.guild_permissions.administrator if message.guild else False

    # Log all messages in main channel
    if is_main_channel:
        log_message(message.author.display_name, message.content)

    # Always process commands first
    await bot.process_commands(message)

    # Check if should respond: must be mentioned or start with "jenny"
    was_mentioned = bot.user in message.mentions
    starts_with_name = message.content.strip().lower().startswith("jenny")

    if not (was_mentioned or starts_with_name):
        return

    # Only respond if in main channel OR user is admin
    if not is_main_channel and not is_admin:
        return  # Silently ignore in non-main channels for non-admins

    user_input = message.content
    user_input = user_input.replace(f"<@{bot.user.id}>", "")
    user_input = user_input.replace(f"<@!{bot.user.id}>", "")
    user_input = user_input.strip()

    if not user_input:
        try:
            await message.reply("heyyy what's up")
        except Exception as e:
            print(f"Could not send reply: {e}")
        return

    username = message.author.display_name
    user_id = str(message.author.id)  # Ensure consistent string conversion

    user_history = get_user_history(user_id)
    log_context = get_recent_log_text()

    # Check if user is replying to a message
    reply_context = None
    if message.reference and message.reference.message_id:
        try:
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            reply_context = f"The user is replying to this message: {referenced_message.author.display_name}: {referenced_message.content}"
        except Exception as e:
            print(f"Could not fetch referenced message: {e}")
            pass  # If we can't fetch the referenced message, just ignore it

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    if log_context:
        messages.append({
            "role": "system",
            "content":
                f"Real recent server chat log (last ~{GLOBAL_LOG_CONTEXT_HOURS}h, timestamped, from everyone):\n"
                f"{log_context}"
        })

    lowered = user_input.lower()

    if any(
        phrase in lowered
        for phrase in (
            "last online",
            "last active",
            "last seen",
            "last message",
            "last talked",
            "last spoke",
        )
    ):
        result = None

        for candidate in guess_target_name(user_input):
            found = await search_last_message(message.channel, candidate)

            if found:
                timestamp = found.created_at.strftime("%b %d, %H:%M UTC")

                result = (
                    f"Search result: the most recent message found from a user "
                    f"matching '{candidate}' was sent at {timestamp}, "
                    f'saying: "{found.content}"'
                )
                break

        if result is None:
            result = (
                "Search result: no matching user or recent messages were found "
                "for that query."
            )

        messages.append({
            "role": "system",
            "content": result
        })

    messages.extend(user_history)
    
    # Add reply context if exists
    if reply_context:
        messages.append({
            "role": "system",
            "content": reply_context
        })
    
    messages.append({
        "role": "user",
        "content": f"{username}: {user_input}"
    })

    image_url = None

    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            image_url = attachment.url
            break

    async with message.channel.typing():
        try:
            if image_url:
                reply = await generate_vision(messages, image_url)
            else:
                reply = await generate(messages)

        except Exception as e:
            print(f"Error generating response: {e}")
            reply = "ugh my brain just glitched, say that again?"

    await message.reply(reply)

    user_history.append({
        "role": "user",
        "content": f"{username}: {user_input}"
    })

    user_history.append({
        "role": "assistant",
        "content": reply
    })

    user_history = user_history[-MAX_HISTORY_PER_USER:]

    save_user_history(
        str(user_id),  # Ensure consistent string conversion
        username,
        user_history,
    )

    log_message("Jenny", reply)


bot.run(DISCORD_TOKEN)