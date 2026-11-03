import os
import re
import asyncio
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
import time

from runtime_logging import configure_runtime_logging

configure_runtime_logging()

import discord
import discord.utils
from discord.ext import commands
from dotenv import load_dotenv

from ai import generate, analyze_image, transcribe_audio_attachment, looks_like_vision_refusal, split_into_discord_chunks
from utils import extract_corrected_response, looks_like_singing
from database import (
    log_message,
    get_recent_log_text,
    get_user_history,
    save_user_history,
    get_last_message_timestamp,
    update_last_message_timestamp,
    get_main_channel_id,
    set_main_channel_id,
    get_logs_channel_id,
    set_logs_channel_id,
    get_setting,
    set_setting,
    save_user_profile,
    get_user_profile,
    get_user_profile_history,
    get_all_user_profiles,
    get_recent_profile_changes,
    find_user_by_name,
    format_user_profile_for_context,
    increment_message_count,
    should_trigger_memory_maintenance,
    get_messages_for_maintenance,
    get_memory_maintenance_info,
    initialize_changelog,
    log_dm_text,
    log_dm_voice,
    get_recent_dm_text,
    get_conversation_history,
    save_conversation_history,
    clear_conversation_history,
    clear_user_conversations,
    get_token_usage,
    search_chat_messages,
    get_recent_channel_messages,
    get_last_user_message,
    save_image_context,
    get_latest_image_context,
    get_recent_voice_chat,
    cleanup_expired_records,
    get_combined_user_summary,
)
from discord_commands import setup_commands, make_pack_trivia, _read_pack_mods
from search import perform_search

from prompt_builder import build_text_prompt, get_relevant_user_context, limit_history_by_tokens
from rich_presence import run_minecraft_presence

# Import memory maintenance
import memory_maintenance

# Add RAG integration path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from jenny_rag_integration import get_rag_context, prewarm_jenny_rag
    RAG_AVAILABLE = True
    print("RAG integration loaded successfully")
except ImportError:
    RAG_AVAILABLE = False
    print("RAG integration not available, using basic modpack context only")

# Import API server for voice integration
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from jenny_api_server import app, set_jenny_functions, start_api_server
    API_AVAILABLE = True
    print("API server module loaded successfully")
except ImportError:
    API_AVAILABLE = False
    print("API server module not available - voice integration disabled")

# Import requests for voice service communication
REQUESTS_AVAILABLE = True  # Already imported at top of file

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Startup timing tracking
startup_start = time.time()
print(f"[STARTUP] Starting at {datetime.now(timezone.utc).isoformat()}")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable is not set. Please check your .env file.")

print(f"[STARTUP] Environment loaded in {(time.time() - startup_start)*1000:.0f}ms")

# Raw per-user history kept verbatim in every prompt
RAW_HISTORY_KEEP = 10
GLOBAL_LOG_CONTEXT_HOURS = 24
MESSAGE_SEARCH_LIMIT = 3000

STOPWORDS = {
    "jenny", "when", "was", "is", "did", "does", "anyone", "someone", "can",
    "you", "see", "check", "last", "online", "active", "seen", "message",
    "messaged", "talked", "spoke", "time", "the", "a", "an", "in", "on",
    "at", "were", "has", "have", "had", "who", "what", "for",
}


# Shared classifier for modpack RAG lookup and web fallback.
from utils import (
    MODPACK_KEYWORDS,
    is_modpack_related,
    NEED_SEARCH_PATTERN,
    FALLBACK_REPLY,
    extract_search_query,
    sanitize_final_reply,
    should_retrieve_modpack_context
)

# Alias for backward compatibility
_is_modpack_related = is_modpack_related
_extract_search_query = extract_search_query
_sanitize_final_reply = sanitize_final_reply
_NEED_SEARCH_PATTERN = NEED_SEARCH_PATTERN

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
# Privileged intents - now enabled in Discord Developer Portal
intents.members = True  # Required for member join/update events (user profiles)
# intents.presences = False  # Disabled - not used, saves memory (~20-30MB)

bot = commands.Bot(command_prefix="!", intents=intents)

setup_commands(bot)

# Voice functionality moved to Node.js service
# No Python voice integration - discord-ext-voice_recv caused issues
VOICE_AVAILABLE = False

# API server thread for voice integration
api_server_thread = None
maintenance_task: Optional[asyncio.Task] = None
profiles_task: Optional[asyncio.Task] = None
rag_prewarm_task: Optional[asyncio.Task] = None
command_sync_complete = False
last_retention_cleanup: Optional[datetime] = None
presence_task: Optional[asyncio.Task] = None


def guess_target_name(text: str) -> List[str]:
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [
        word
        for word in words
        if word not in STOPWORDS and len(word) >= 3
    ]


async def search_last_message(channel: discord.abc.Messageable, name_query: str) -> Optional[discord.Message]:
    try:
        async for msg in channel.history(limit=MESSAGE_SEARCH_LIMIT):
            if name_query in msg.author.display_name.lower():
                return msg
    except Exception as e:
        print(f"Error searching messages: {e}")
    return None


async def _prewarm_rag() -> None:
    """Warm a non-empty RAG index in the background after Discord is ready."""
    try:
        warmed = await asyncio.to_thread(prewarm_jenny_rag)
        if warmed:
            print("[RAG] Existing index pre-warmed in the background")
        else:
            print("[RAG] Pre-warm skipped; no searchable index is available")
    except Exception as e:
        print(f"[RAG] Pre-warm failed: {e}")


async def _fetch_profiles_background() -> None:
    """Fetch user profiles in background to speed up startup"""
    try:
        for guild in bot.guilds:
            print(f"[PROFILES] Fetching profiles for guild: {guild.name}")
            await fetch_and_save_all_profiles(guild)
    except Exception as e:
        print(f"[PROFILES] Background profile fetch failed: {e}")


async def _automatic_memory_maintenance() -> None:
    """Automatically summarize active conversations every 15 minutes."""
    global last_retention_cleanup
    while True:
        try:
            print("[MAINTENANCE] Checking active conversation streams...")

            if last_retention_cleanup is None or (datetime.now(timezone.utc) - last_retention_cleanup).total_seconds() >= 86400:
                deleted = await asyncio.to_thread(cleanup_expired_records, int(os.getenv("DATA_RETENTION_DAYS", "90")))
                last_retention_cleanup = datetime.now(timezone.utc)
                print(f"[MAINTENANCE] Retention cleanup completed: {deleted}")

            from database import should_trigger_memory_maintenance, get_dm_sessions
            # Check text channels
            for guild in bot.guilds:
                for channel in guild.text_channels:
                    if should_trigger_memory_maintenance(str(channel.id), stream_type="text"):
                        print(f"[MAINTENANCE] Triggering text maintenance for channel {channel.name}")
                        await memory_maintenance.run_memory_maintenance_for_stream(
                            str(channel.id), "text", memory_scope=f"guild:{guild.id}")

                # Check voice streams by guild ID
                if should_trigger_memory_maintenance(str(guild.id), stream_type="voice"):
                    print(f"[MAINTENANCE] Triggering voice maintenance for guild {guild.name}")
                    await memory_maintenance.run_memory_maintenance_for_stream(
                        str(guild.id), "voice", memory_scope=f"guild:{guild.id}")

            for session_id in get_dm_sessions():
                if should_trigger_memory_maintenance(session_id, stream_type="dm_text"):
                    await memory_maintenance.run_memory_maintenance_for_stream(session_id, "dm_text")
                if should_trigger_memory_maintenance(session_id, stream_type="dm_voice"):
                    await memory_maintenance.run_memory_maintenance_for_stream(session_id, "dm_voice")
        except Exception as e:
            print(f"[MAINTENANCE] Automatic maintenance failed: {e}")
        await asyncio.sleep(900)


@bot.event
async def on_ready() -> None:
    global maintenance_task, profiles_task, rag_prewarm_task, command_sync_complete, presence_task
    ready_start = time.time()
    print("=== BOT STARTED ===")
    if bot.user is not None:
        print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Process ID: {os.getpid()}")
    print(f"[STARTUP] Discord connection ready in {(time.time() - ready_start)*1000:.0f}ms")

    if not command_sync_complete:
        sync_start = time.time()
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash command(s) globally")
            # Previous TEST_GUILD_ID runs left a second guild-scoped copy of
            # each command. Global sync never removes those copies, so clear
            # stale guild registrations from every server this bot is in.
            for joined_guild in bot.guilds:
                scope = discord.Object(id=joined_guild.id)
                bot.tree.clear_commands(guild=scope)
                removed = await bot.tree.sync(guild=scope)
                print(f"Cleared {len(removed)} guild-scoped command(s) from {joined_guild.name}")
            command_sync_complete = True
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")
        print(f"[STARTUP] Slash commands synced in {(time.time() - sync_start)*1000:.0f}ms")

    print("Jenny is online and ready!")
    print(f"[STARTUP] Total startup time: {(time.time() - startup_start)*1000:.0f}ms")

    # Keep a single process-lifetime presence loop. on_ready may fire again
    # after a gateway resume, so do not start duplicate updater tasks.
    if presence_task is None or presence_task.done():
        presence_task = asyncio.create_task(run_minecraft_presence(bot))

    # Warm a non-empty index off the event loop so the first Minecraft question
    # does not pay the embedding model's cold-start cost.
    if RAG_AVAILABLE and (rag_prewarm_task is None or rag_prewarm_task.done()):
        rag_prewarm_task = asyncio.create_task(_prewarm_rag())

    if bot.guilds:
        for joined_guild in bot.guilds:
            main_channel_id = get_main_channel_id(str(joined_guild.id))
            if main_channel_id:
                print(f"Main channel for {joined_guild.name}: {main_channel_id}")
            else:
                print(f"No main channel configured for {joined_guild.name}. Use /setmainchannel there.")
    else:
        print("The bot is not currently in any servers.")
    print("==================")
    
    # Fetch and save all user profiles in the guild (requires members intent)
    # Moved to background task to speed up startup
    if intents.members and (profiles_task is None or profiles_task.done()):
        profiles_task = asyncio.create_task(_fetch_profiles_background())

    # Start the automatic memory and retention scheduler.
    if maintenance_task is None or maintenance_task.done():
        maintenance_task = asyncio.create_task(_automatic_memory_mainten message.author  # Default to sender if no user specified
                    
                    if user:
                        history = get_user_profile_history(str(user.id), limit=20, guild_id=str(message.guild.id))
                        if history:
                            text = "\n".join(f"{item['timestamp']}: {item['field_name']} changed from {item['old_value'] or 'none'} to {item['new_value'] or 'none'}" for item in history)
                            chunks = split_into_discord_chunks(text)
                            for chunk in chunks:
                                await message.reply(chunk)
                        else:
                            await message.reply(f"No saved profile history for {user.mention}.")
                    else:
                        print(f"[COMMAND] User not found")
                    
                    # Send the natural message without the command
                    if reply_without_cmd:
                        chunks = split_into_discord_chunks(reply_without_cmd)
                        await message.reply(chunks[0])
                        for chunk in chunks[1:]:
                            await message.reply(chunk)
                    
                elif command == "recentchanges":
                    print("[COMMAND] Viewing recent profile changes")
                    # Execute recent changes logic directly
                    changes = get_recent_profile_changes(hours=24, limit=25, guild_id=str(message.guild.id))
                    if changes:
                        text = "\n".join(f"{item['timestamp']}: <@{item['user_id']}>: {item['field_name']} changed" for item in changes)
                        for chunk in split_into_discord_chunks(text):
                            await message.reply(chunk)
                    else:
                        await message.reply("No profile changes in the last 24 hours.")
                    # Send the natural message without the command
                    if reply_without_cmd:
                        chunks = split_into_discord_chunks(reply_without_cmd)
                        await message.reply(chunks[0])
                        for chunk in chunks[1:]:
                            await message.reply(chunk)
                    
                elif command == "finduser":
                    print("[COMMAND] Finding user by name")
                    # Extract name from natural message
                    name_match = re.search(r'find\s+(?:user\s+)?@?(\w+)', reply_without_cmd or "", re.IGNORECASE)
                    
                    if name_match:
                        username = name_match.group(1)
                        # Execute find user logic directly
                        from database import find_user_by_name
                        users = find_user_by_name(username, guild_id=str(message.guild.id) if message.guild else None)
                        if users:
                            text = "\n".join(f"{item['display_name']} (@{item['username']}) | {item['user_id']}" for item in users)
                            await message.reply(text[:1900])
                        else:
                            await message.reply(f"No members matched {username!r}.")
                    else:
                        print("[COMMAND] Missing username for finduser command")
                    
                    # Send the natural message without the command
                    if reply_without_cmd:
                        chunks = split_into_discord_chunks(reply_without_cmd)
                        await message.reply(chunks[0])
                        for chunk in chunks[1:]:
                            await message.reply(chunk)
                    
                else:
                    print(f"[COMMAND] Unknown command: {command}")
                    # Unknown command, just send the reply as-is (including the CMD: prefix will be visible)
                    pass
            
            # After executing all commands, return since we handled everything
            return
        else:
            print(f"[COMMAND] No CMD: prefix found, treating as normal reply")
            cmd_processed = False
    
    # Remove CMD: prefix if it wasn't recognized as a command (fallback)
    if not cmd_processed:
        reply = cmd_pattern.sub('', reply).strip()

    # Handle reply mode
    print(f"[SEND] Reply mode: {reply_mode}")
    
    # Check if voice service is available before attempting voice routing
    voice_available = await asyncio.to_thread(check_voice_service_available)
    print(f"[Voice] Voice service available: {voice_available}")
    
    # Check if bot is actually in voice channel
    bot_in_vc = await asyncio.to_thread(check_bot_in_voice_channel, str(message.guild.id))
    print(f"[Voice] Bot in voice channel: {bot_in_vc}")
    
    if reply_mode == "vc":  # Voice only mode
        print(f"[Voice] Reply mode is voice-only")
        if not voice_available:
            print(f"[Voice] Voice service unavailable, falling back to text response")
            chunks = split_into_discord_chunks(reply)
            print(f"[SEND] Sending {len(chunks)} chunk(s) to Discord (fallback)")
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.reply(chunk)
            await message.reply(embed=discord.Embed(title="Voice service unavailable", description="I sent the reply in chat because the voice service is offline.", color=discord.Color.red()))
        elif not bot_in_vc:
            print(f"[Voice] Bot not in voice channel, falling back to text response")
            chunks = split_into_discord_chunks(reply)
            print(f"[SEND] Sending {len(chunks)} chunk(s) to Discord (not in VC)")
            await message.reply(chunks[0])
            for chunk in chunks[1:]:
                await message.reply(chunk)
            await message.reply(embed=discord.Embed(title="Jenny is not in voice", description="I sent the reply in chat. Ask me to join a voice channel before using voice-only replies.", color=discord.Color.red()))
        else:
            # Route to voice service for TTS playback
            try:
                voice_service_url = "http://127.0.0.1:8000/voice/tts"
                requests.post(voice_service_url, json={
                    "text": reply,
                    "guild_id": str(message.guild.id),
                    "user_id": user_id,
                }, timeout=4).raise_for_status()
                print(f"[Voice] Routed to voice service for TTS playback")
            except Exception as e:
                print(f"[Voice] Failed to route to voice service: {e}")
                # Fallback to text if voice routing fails
                print(f"[Voice] Voice routing failed, falling back to text response")
                chunks = split_into_discord_chunks(reply)
                await message.reply(chunks[0])
                for chunk in chunks[1:]:
                    await message.reply(chunk)
                await message.reply(embed=discord.Embed(title="Voice reply failed", description=f"I sent the reply in chat instead. {str(e)[:500]}", color=discord.Color.red()))
    elif reply_mode == "both":  # Both mode
        print(f"[Voice] Reply mode is both - sending text response")
        chunks = split_into_discord_chunks(reply)
        print(f"[SEND] Sending {len(chunks)} chunk(s) to Discord")
        await message.reply(chunks[0])
        for chunk in chunks[1:]:
            await message.reply(chunk)
        
        # Only route to voice if service is available AND bot is in VC
        if voice_available and bot_in_vc:
            try:
                voice_service_url = "http://127.0.0.1:8000/voice/tts"
                requests.post(voice_service_url, json={
                    "text": reply,
                    "guild_id": str(message.guild.id),
                    "user_id": user_id,
                }, timeout=4)
                print(f"[Voice] Routed to voice service for TTS playback")
            except Exception as e:
                print(f"[Voice] Failed to route to voice service: {e}")
        else:
            if not voice_available:
                print(f"[Voice] Voice service unavailable, skipping voice playback")
                await message.reply(embed=discord.Embed(title="Voice service unavailable", description="I sent the reply in chat, but could not speak it because the voice service is offline.", color=discord.Color.red()))
            else:
                await message.reply(embed=discord.Embed(title="Jenny is not in voice", description="I sent the reply in chat, but Jenny is not connected to a voice channel.", color=discord.Color.red()))
    else:  # Chat mode (default)
        print(f"[SEND] Chat mode - sending text response")
        chunks = split_into_discord_chunks(reply)
        print(f"[SEND] Sending {len(chunks)} chunk(s) to Discord")
        await message.reply(chunks[0])
        for chunk in chunks[1:]:
            await message.reply(chunk)

    user_history.extend([
        {"role": "user", "content": f"{username}: {user_input}"},
        {"role": "assistant", "content": reply},
    ])

    # Update last message timestamp
    update_last_message_timestamp(user_id)

    save_conversation_history(conversation_id, user_id, username, user_history, limit=24)

    log_message("Jenny", reply, str(bot.user.id) if bot.user else None,
                str(message.channel.id), str(message.guild.id))
    await send_configured_reply_log(message, reply)


# Start API server in background thread for voice integration
if API_AVAILABLE:
    def run_api_server():
        print("[API] Starting API server on http://127.0.0.1:8000")
        set_jenny_functions(generate, RAG_AVAILABLE, get_live_role_context)
        start_api_server(host="127.0.0.1", port=8000)
    
    api_server_thread = threading.Thread(target=run_api_server, daemon=True)
    api_server_thread.start()
    print("[API] API server thread started")


def check_voice_service_available() -> bool:
    """Check if the voice service is online and available"""
    if not REQUESTS_AVAILABLE:
        return False
    
    try:
        response = requests.get("http://127.0.0.1:8000/health", timeout=2)
        if response.status_code != 200:
            return False
        health = response.json()
        return bool(health.get("voice_service_online", False))
    except Exception as e:
        print(f"[Voice] Voice service health check failed: {e}")
        return False


def check_bot_in_voice_channel(guild_id: str) -> bool:
    """Check if the bot is currently in a voice channel for the given guild"""
    if not REQUESTS_AVAILABLE:
        return False
    
    try:
        # Use the new voice status endpoint to check actual connection state
        response = requests.get(f"http://127.0.0.1:8000/voice/status/{guild_id}", timeout=2)
        if response.status_code == 200:
            data = response.json()
            return data.get("in_voice", False)
        return False
    except Exception as e:
        print(f"[Voice] Could not verify voice connection status: {e}")
        return False

bot.run(DISCORD_TOKEN)
