"""
Memory maintenance system for Jenny bot
Automatically summarizes conversations and updates long-term memory
"""

import json
from json import JSONDecodeError
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Dict
from database import (
    get_channel_memory, set_channel_memory, get_memory_maintenance_info,
    update_memory_maintenance, should_trigger_memory_maintenance, defer_memory_maintenance,
    get_messages_for_maintenance, get_voice_messages_for_maintenance,
    log_message,
    get_dm_text_for_maintenance, get_dm_voice_for_maintenance,
    set_scoped_user_summary, get_combined_user_summary,
    get_recent_user_daily_summaries, set_user_daily_summary
)
from prompt_builder import build_memory_prompt
from ai import generate_memory_maintenance as ai_generate


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

        # DM logs contain both participants for context, but Jenny's messages
        # must never be treated as facts about the human user.
        source_messages = messages
        if stream_type == "dm_text":
            messages = [row for row in source_messages if row.get("direction") == "incoming"]
            if not messages:
                cursor_id = source_messages[-1].get("id", last_message_id)
                update_memory_maintenance(channel_id, stream_type, cursor_id, len(source_messages))
                print(f"[Memory] Skipped {len(source_messages)} Jenny DM replies; no user facts to save")
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

        # Dated summaries preserve short-term context for a week. Only dates
        # represented in this batch may be updated by the model.
        today = datetime.now(timezone.utc).date()
        cutoff_day = today - timedelta(days=6)
        allowed_summary_dates: Dict[str, list[str]] = {user_id: [] for user_id in allowed_user_ids}
        for msg in messages:
            user_id = str(msg.get("user_id") or "")
            raw_timestamp = str(msg.get("timestamp") or "")
            if user_id not in allowed_summary_dates:
                continue
            try:
                day = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00")).date()
            except ValueError:
                day = today
            if cutoff_day <= day <= today:
                allowed_summary_dates[user_id].append(day.isoformat())
        for user_id in allowed_summary_dates:
            allowed_summary_dates[user_id] = sorted(set(allowed_summary_dates[user_id]))

        # Get current user memories
        current_user_memories: Dict[str, str] = {}
        current_daily_user_summaries: Dict[str, Dict[str, str]] = {}
        for user_id in unique_users:
            current_user_memories[user_id] = get_combined_user_summary(user_id, memory_scope)
            current_daily_user_summaries[user_id] = get_recent_user_daily_summaries(user_id, 7)

        # Build the memory maintenance prompt
        memory_prompt = build_memory_prompt(
            messages_to_summarize=messages,
            current_channel_summary=current_channel_summary,
            current_user_memories=current_user_memories,
            channel_id=channel_id,
            stream_type=stream_type,
            allowed_user_ids=allowed_user_ids,
            current_daily_user_summaries=current_daily_user_summaries,
            allowed_summary_dates=allowed_summary_dates,
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
                current_daily_user_summaries=current_daily_user_summaries,
                allowed_summary_dates=allowed_summary_dates,
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
        raw_daily_updates = memory_update.get("daily_summaries", {})
        if isinstance(raw_daily_updates, dict):
            for user_id, summaries in raw_daily_updates.items():
                user_id = str(user_id)
                if user_id not in allowed_summary_dates or not isinstance(summaries, dict):
                    continue
                for day, summary in summaries.items():
                    day = str(day)
                    if (day in allowed_summary_dates[user_id] and isinstance(summary, str)
                            and summary.strip()):
                        set_user_daily_summary(user_id, day, summary)
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
            # Keep exactly one canonical row. Discord snowflake IDs link the
            # same person across DMs and guilds without copying summaries.
            set_scoped_user_summary(f"user:{user_id}", user_id, user_memory)
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
