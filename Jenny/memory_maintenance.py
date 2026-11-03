"""
Memory maintenance system for Jenny bot
Automatically summarizes conversations and updates long-term memory
"""

import json
from json import JSONDecodeError
from typing import Optional, Callable, Dict
from database import (
    get_channel_memory, set_channel_memory, get_memory_maintenance_info,
    update_memory_maintenance, should_trigger_memory_maintenance, defer_memory_maintenance,
    get_messages_for_maintenance, get_voice_messages_for_maintenance,
    get_user_summary, set_user_summary, log_message,
    get_dm_text_for_maintenance, get_dm_voice_for_maintenance,
    set_scoped_user_summary, get_combined_user_summary
)
from prompt_builder import build_memory_prompt
from ai import generate as ai_generate


async def run_memory_maintenance_for_stream(channel_id: str, stream_type: str = "text",
                                            generate_func: Optional[Callable] = None,
                                            memory_scope: Optional[str] = None) -> bool:
    """
    Run memory maintenance for a specific channel and stream type (text or voice)

    Args:
        channel_id: The channel/guild ID to perform maintenance for
        stream_type: Either "text" for chat messages or "voice" for voice transcripts
        generate_func: The AI generation function to use (uses ai.generate if not provided)

    Returns:
        True if maintenance was performed, False otherwise
    """
    if generate_func is None:
        generate_func = ai_generate

    try:
        if memory_scope is None and stream_type.startswith("dm_"):
            memory_scope = f"dm:{channel_id.replace('dm_', '')}"
        elif memory_scope is None and stream_type == "voice":
            memory_scope = f"guild:{channel_id}"
        # New streams receive an initial summary after activity is detected.
        # Later summaries run at 25 new records or six hours of activity.
        if not should_trigger_memory_maintenance(channel_id, stream_type=stream_type, message_threshold=100, hours_threshold=24):
            return False

        print(f"[Memory] Starting memory maintenance for {stream_type} stream in {channel_id}")
        log_message("Jenny (System)", f"Starting memory maintenance for {stream_type} stream in {channel_id}", None, channel_id)

        # Get messages to summarize based on stream type
        maintenance_info = get_memory_maintenance_info(channel_id, stream_type)
        last_message_id = int(maintenance_info.get("last_message_id_processed") or 0)

        batch_limit = 30
        if stream_type == "text":
            messages = get_messages_for_maintenance(channel_id, limit=batch_limit)
        elif stream_type == "voice":
            messages = get_voice_messages_for_maintenance(channel_id, limit=batch_limit)
        elif stream_type == "dm_text":
            messages = get_dm_text_for_maintenance(channel_id, after_id=last_message_id, limit=batch_limit)
        elif stream_type == "dm_voice":
            messages = get_dm_voice_for_maintenance(channel_id, after_id=last_message_id, limit=batch_limit)
        else:
            print(f"[Memory] Unknown stream type: {stream_type}")
            return False

        if not messages:
            print(f"[Memory] No new messages to summarize for {stream_type} stream in {channel_id}")
            # Expired detailed logs may leave a stale counter. Clear it to avoid
            # repeatedly waking an empty stream every scheduler interval.
            update_memory_maintenance(channel_id, stream_type, last_message_id, 0, reset_pending=True)
            return False

        # Get current channel summary (skip for DM streams)
        current_channel_summary = ""
        if not stream_type.startswith("dm_"):
            current_channel_summary = get_channel_memory(channel_id)

        # Get unique users from messages
        unique_users: set = set()
        for msg in messages:
            if msg.get("user_id"):
                unique_users.add(str(msg["user_id"]))
        if stream_type.startswith("dm_") and channel_id.startswith("dm_"):
            dm_user_id = channel_id[len("dm_"):]
            if dm_user_id.isdigit():
                unique_users.add(dm_user_id)
        allowed_user_ids = sorted(unique_users)

        # Get current user memories
        current_user_memories: Dict[str, str] = {}
        for user_id in unique_users:
            current_user_memories[user_id] = get_combined_user_summary(user_id, memory_scope)

        # Build the memory maintenance prompt
        memory_prompt = build_memory_prompt(
            messages_to_summarize=messages,
            current_channel_summary=current_channel_summary,
            current_user_memories=current_user_memories,
            channel_id=channel_id,
            stream_type=stream_type,
            allowed_user_ids=allowed_user_ids,
        )

        # Call AI to perform memory maintenance
        print(f"[Memory] Sending {len(messages)} {stream_type} messages to AI for summarization")
        log_message("Jenny (System)", f"Sending {len(messages)} {stream_type} messages to AI for summarization", None, channel_id)
        def parse_memory_response(raw: str):
            try:
                value = json.loads(raw)
            except JSONDecodeError:
                start = raw.find("{")
                if start < 0:
                    return None
                try:
                    value, _ = json.JSONDecoder().raw_decode(raw[start:])
                except JSONDecodeError:
                    return None
            return value if isinstance(value, dict) else None

        ai_response = await generate_func(memory_prompt, max_tokens=900)
        memory_update = parse_memory_response(ai_response)
        processed_messages = messages
        if memory_update is None and len(messages) > 10:
            # Retry a smaller prefix when a provider truncates its JSON output.
            processed_messages = messages[:10]
            retry_prompt = build_memory_prompt(
                messages_to_summarize=processed_messages,
                current_channel_summary=current_channel_summary,
                current_user_memories=current_user_memories,
                channel_id=channel_id,
                stream_type=stream_type,
                allowed_user_ids=allowed_user_ids,
            )
            print(f"[Memory] Retrying malformed {stream_type} summary with 10 records")
            ai_response = await generate_func(retry_prompt, max_tokens=700)
            memory_update = parse_memory_response(ai_response)

        if memory_update is None:
            retry_after = defer_memory_maintenance(channel_id, stream_type)
            print(f"[Memory] Invalid summary JSON; retry deferred until {retry_after.isoformat()}")
            return False

        raw_user_updates = memory_update.get("user_memories", {})
        if not isinstance(raw_user_updates, dict):
            raw_user_updates = {}
        user_updates = {
            str(user_id): str(value).strip()[:450]
            for user_id, value in raw_user_updates.items()
            if str(user_id) in allowed_user_ids and isinstance(value, str) and value.strip()
        }
        # A DM has exactly one participant. Correct malformed older output that
        # used a placeholder key such as "unknown" instead of their real ID.
        if stream_type.startswith("dm_") and len(allowed_user_ids) == 1 and not user_updates:
            candidate = next((value for value in raw_user_updates.values()
                              if isinstance(value, str) and value.strip()), None)
            if candidate:
                user_updates[allowed_user_ids[0]] = candidate.strip()[:450]

        channel_summary_value = memory_update.get("channel_summary")
        if not stream_type.startswith("dm_") and not isinstance(channel_summary_value, str):
            retry_after = defer_memory_maintenance(channel_id, stream_type)
            print(f"[Memory] Summary omitted channel memory; retry deferred until {retry_after.isoformat()}")
            return False

        if not stream_type.startswith("dm_"):
            set_channel_memory(channel_id, channel_summary_value.strip()[:2000])
            print(f"[Memory] Updated channel summary for {channel_id}")
            log_message("Jenny (System)", f"Updated channel summary for {channel_id}", None, channel_id)

        for user_id, user_memory in user_updates.items():
            # Keep the merged summary in the shared user scope so the same
            # Discord account can recall it in DMs, voice, and any guild.
            set_scoped_user_summary(f"user:{user_id}", user_id, user_memory)
            if memory_scope:
                set_scoped_user_summary(memory_scope, user_id, user_memory)
            else:
                set_user_summary(user_id, user_memory)
            print(f"[Memory] Updated memory for user {user_id}")
            log_message("Jenny (System)", f"Updated memory for user {user_id}", None, channel_id)

        processed_last_id = processed_messages[-1].get("id", last_message_id)
        update_memory_maintenance(channel_id, stream_type, processed_last_id, len(processed_messages))
        print(f"[Memory] Memory maintenance completed for {stream_type} stream in {channel_id}")
        log_message("Jenny (System)", f"Memory maintenance completed for {stream_type} stream in {channel_id}", None, channel_id)
        return True

    except Exception as e:
        print(f"[Memory] Error during memory maintenance: {e}")
        retry_after = defer_memory_maintenance(channel_id, stream_type)
        print(f"[Memory] Retry deferred until {retry_after.isoformat()}")
        log_message("Jenny (System)", f"Error during memory maintenance for {stream_type} stream in {channel_id}: {e}", None, channel_id)
        return False


async def run_memory_maintenance_for_channel(channel_id: str, generate_func: Optional[Callable] = None,
                                             memory_scope: Optional[str] = None) -> bool:
    """
    Run memory maintenance for both text and voice streams in a channel

    Args:
        channel_id: The channel ID to perform maintenance for
        generate_func: The AI generation function to use (uses ai.generate if not provided)

    Returns:
        True if any maintenance was performed, False otherwise
    """
    # Run maintenance for text stream
    text_done = await run_memory_maintenance_for_stream(channel_id, "text", generate_func, memory_scope)

    # Run maintenance for voice stream (using guild_id)
    voice_done = await run_memory_maintenance_for_stream(channel_id, "voice", generate_func, memory_scope)

    return text_done or voice_done




