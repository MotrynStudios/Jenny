"""
Prompt builder for Jenny bot - constructs modular prompts based on operation type
"""

import json
from typing import List, Dict, Optional
from Prompts import CORE_PROMPT, TEXT_MODE_PROMPT, VOICE_MODE_PROMPT, MEMORY_MAINTENANCE_PROMPT
from database import (format_user_profile_for_context, get_combined_user_summary,
                      get_recent_user_daily_summaries)


def build_text_prompt(
    reply_context: Optional[str] = None,
    image_context: Optional[str] = None,
    user_profiles: Optional[Dict[str, str]] = None,
    channel_summary: Optional[str] = None,
    current_time: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Build prompt for text Discord interactions.
    Memory sections have token limits:
    - Channel summary + user memory: 1500 tokens
    - Recent messages: 1000 tokens
    Other sections (prompt, current message, reply context, image context) are unrestricted.
    
    Args:
        reply_context: Replied-to message content if applicable
        image_context: Image description if applicable
        user_profiles: Dict of user_id -> profile context strings
        channel_summary: Long-term channel memory summary
        current_time: Current date/time string
    
    Returns:
        List of message dicts for AI request
    """
    messages: List[Dict[str, str]] = []
    
    # Build system prompt with CORE + TEXT_MODE instructions
    system_prompt: str = CORE_PROMPT + "\n\n" + TEXT_MODE_PROMPT
    
    # Add current time if provided
    if current_time:
        system_prompt += f"\n\nCurrent date and time: {current_time}"
    
    messages.append({"role": "system", "content": system_prompt})
    
    # Build combined context (channel summary + user profiles)
    # This section has a 1500-token limit
    combined_context: str = ""
    
    # Add channel summary if provided
    if channel_summary:
        combined_context += f"Channel memory (long-term summary):\n{channel_summary}\n"
    
    # Add user profiles if provided
    if user_profiles:
        for user_id, profile_context in user_profiles.items():
            if profile_context:
                combined_context += f"{profile_context}\n"
    
    # Enforce 1500-token limit on combined context (channel summary + user memory)
    if combined_context:
        if estimate_tokens(combined_context) > 1500:
            combined_context = combined_context[:6000] + "... [truncated for token limit]"
        messages.append({"role": "system", "content": combined_context})
    
    # Add reply context if provided (unrestricted)
    if reply_context:
        messages.append({
            "role": "system",
            "content": f"Referenced/replied-to message:\n{reply_context}"
        })
    
    # Add image context if provided (unrestricted)
    if image_context:
        messages.append({
            "role": "system",
            "content": f"Referenced image description:\n{image_context}"
        })
    
    return messages


def build_voice_prompt(
    transcript: str,
    username: str,
    recent_messages: List[Dict[str, str]],
    recent_voice_context: Optional[str] = None,
    user_profiles: Optional[Dict[str, str]] = None,
    channel_summary: Optional[str] = None,
    current_time: Optional[str] = None
) -> List[Dict[str, str]]:
    """
    Build prompt for voice interactions.
    Memory sections have token limits:
    - Channel summary + user memory: 1500 tokens
    - Recent messages: 1000 tokens
    Other sections (prompt, transcript, voice context) are unrestricted.
    
    Args:
        transcript: The transcribed voice message
        username: The user who spoke
        recent_messages: List of recent conversation messages
        recent_voice_context: Recent voice chat context if applicable
        user_profiles: Dict of user_id -> profile context strings
        channel_summary: Long-term channel memory summary
        current_time: Current date/time string
    
    Returns:
        List of message dicts for AI request
    """
    messages: List[Dict[str, str]] = []
    
    # Build system prompt with CORE + VOICE_MODE instructions
    system_prompt: str = CORE_PROMPT + "\n\n" + VOICE_MODE_PROMPT
    
    # Add current time if provided
    if current_time:
        system_prompt += f"\n\nCurrent date and time: {current_time}"
    
    messages.append({"role": "system", "content": system_prompt})
    
    # Build combined context (channel summary + user profiles)
    # This section has a 1500-token limit
    combined_context: str = ""
    
    # Add channel summary if provided
    if channel_summary:
        combined_context += f"Channel memory (long-term summary):\n{channel_summary}\n"
    
    # Add user profiles if provided
    if user_profiles:
        for user_id, profile_context in user_profiles.items():
            if profile_context:
                combined_context += f"{profile_context}\n"
    
    # Enforce 1500-token limit on combined context (channel summary + user memory)
    if combined_context:
        if estimate_tokens(combined_context) > 1500:
            combined_context = combined_context[:6000] + "... [truncated for token limit]"
        messages.append({"role": "system", "content": combined_context})
    
    # Add recent conversation messages with 1000-token limit
    if recent_messages:
        recent_context: str = "Recent conversation:\n"
        for msg in limit_history_by_tokens(recent_messages, 1000):
            recent_context += f"{msg.get('role', 'unknown')}: {msg.get('content', '')}\n"
        messages.append({"role": "system", "content": recent_context})
    
    # Add recent voice chat context if provided (unrestricted)
    if recent_voice_context:
        messages.append({"role": "system", "content": recent_voice_context})
    
    # Add voice transcription instruction (unrestricted)
    messages.append({
        "role": "system",
        "content": "Note: This input came from voice transcription, which may contain errors or mistranscriptions. Please respond helpfully even if the input seems slightly off or unclear. If you cannot understand the input, ask for clarification."
    })
    
    # Add current transcription (unrestricted)
    messages.append({"role": "user", "content": f"{username}: {transcript}"})
    
    return messages


def build_memory_prompt(
    messages_to_summarize: List[Dict[str, str]],
    current_channel_summary: str,
    current_user_memories: Dict[str, str],
    channel_id: Optional[str] = None,
    stream_type: str = "text",
    allowed_user_ids: Optional[List[str]] = None,
    current_daily_user_summaries: Optional[Dict[str, Dict[str, str]]] = None,
    allowed_summary_dates: Optional[Dict[str, List[str]]] = None,
) -> List[Dict[str, str]]:
    """
    Build prompt for memory maintenance operation

    Args:
        messages_to_summarize: List of messages to summarize
        current_channel_summary: Current channel memory summary
        current_user_memories: Dict of user_id -> current user memory
        channel_id: Channel ID for context
        stream_type: Either "text" for chat messages or "voice" for voice transcripts

    Returns:
        List of message dicts for AI request
    """
    messages: List[Dict[str, str]] = []

    # Build system prompt with MEMORY_MAINTENANCE instructions
    system_prompt: str = MEMORY_MAINTENANCE_PROMPT

    # Keep operational context short and provide exact output keys. For DMs,
    # channel summaries are irrelevant and must not be generated.
    context_text = f"Stream: {stream_type}. Allowed user IDs: {', '.join(allowed_user_ids or []) or 'none'}."
    system_prompt += f"\n\n{context_text}"

    messages.append({"role": "system", "content": system_prompt})

    # Add current channel summary
    if current_channel_summary and not stream_type.startswith("dm_"):
        messages.append({
            "role": "system",
            "content": f"Current channel summary (merge and compress; max 500 tokens):\n{current_channel_summary[:2200]}"
        })

    # Add current user memories
    if current_user_memories:
        for user_id, user_memory in current_user_memories.items():
            if user_memory:
                messages.append({
                    "role": "system",
                    "content": f"Current memory for user {user_id} (merge; max 100 tokens):\n{user_memory[:450]}"
                })

    if current_daily_user_summaries:
        for user_id, summaries in current_daily_user_summaries.items():
            if summaries:
                dated_context = "\n".join(f"{day}: {summary}" for day, summary in sorted(summaries.items()))
                messages.append({
                    "role": "system",
                    "content": f"Existing recent daily context for user {user_id}; merge only matching dates:\n{dated_context[:2500]}"
                })

    # Add messages to summarize
    if stream_type in {"voice", "dm_voice"}:
        messages_text: str = "\n".join([
            f"{str(msg.get('timestamp', ''))[:16]} {msg.get('username', 'unknown')}: {str(msg.get('transcript', ''))[:450]}"
            for msg in messages_to_summarize
        ])
    elif stream_type == "dm_text":
        messages_text = "\n".join([
            f"{str(msg.get('timestamp', ''))[:16]} {('Jenny' if msg.get('direction') == 'outgoing' else msg.get('username', 'User'))}: {str(msg.get('content', ''))[:450]}"
            for msg in messages_to_summarize
        ])
    else:
        messages_text: str = "\n".join([
            f"{str(msg.get('timestamp', ''))[:16]} {msg.get('author', 'unknown')}: {str(msg.get('content', ''))[:450]}"
            for msg in messages_to_summarize
        ])

    messages.append({
        "role": "system",
        "content": f"Messages to summarize ({len(messages_to_summarize)} {stream_type} entries):\n{messages_text}"
    })

    # Add the final instruction
    messages.append({
        "role": "user",
        "content": (
            "Return valid JSON with channel_summary, user_memories, and daily_summaries. "
            "For DM streams, omit channel_summary. Use only the supplied user IDs and dates. "
            f"Allowed daily summary dates: {json.dumps(allowed_summary_dates or {}, ensure_ascii=False)}. "
            "daily_summaries must map user IDs to date-keyed concise summaries of conversation context for that date. "
            "Keep recent summaries useful for the past week's follow-ups; keep user_memories durable and under 100 tokens. "
            "Keep channel_summary under 500 tokens."
        )
    })

    return messages


def get_relevant_user_context(user_ids: List[str], guild_id: Optional[str] = None,
                             memory_scope: Optional[str] = None,
                             include_profiles: bool = False) -> Dict[str, str]:
    """
    Get context for relevant users
    
    Args:
        user_ids: List of user IDs to get context for
    
    Returns:
        Dict of user_id -> formatted context string
    """
    user_contexts: Dict[str, str] = {}
    for user_id in user_ids:
        # The stable Discord user ID links their shared memory across DMs and
        # servers. Preserve local-scope memory while older rows migrate forward.
        user_memory = get_combined_user_summary(user_id, memory_scope)
        recent_summaries = get_recent_user_daily_summaries(user_id, 7)
        
        # Profile history can be sizeable and is only needed for profile questions.
        profile_context: str = (format_user_profile_for_context(user_id, guild_id)
                                if include_profiles else "")
        
        # Combine both
        combined_context: str = ""
        if profile_context:
            combined_context += profile_context + "\n"
        if user_memory:
            combined_context += f"Long-term memory: {user_memory}"
        if recent_summaries:
            recent_text = "\n".join(f"{day}: {summary}" for day, summary in sorted(recent_summaries.items()))
            combined_context += f"\nRecent daily conversation summaries (last 7 days):\n{recent_text}"
        
        if combined_context.strip():
            user_contexts[user_id] = combined_context.strip()
    
    return user_contexts


def estimate_tokens(text: str) -> int:
    """
    Rough estimate of token count (4 chars per token approximation)
    
    Args:
        text: Text to estimate tokens for
    
    Returns:
        Estimated token count
    """
    return len(text) // 4


def limit_history_by_tokens(history: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    """Keep the newest complete messages that fit a conservative token budget."""
    selected: List[Dict[str, str]] = []
    used_tokens = 0
    for entry in reversed(history):
        content = str(entry.get("content", ""))
        cost = estimate_tokens(content) + 4  # framing and role overhead
        if selected and used_tokens + cost > max_tokens:
            break
        if cost > max_tokens:
            content = content[:max_tokens * 4]
            cost = estimate_tokens(content) + 4
        selected.append({"role": entry.get("role", "user"), "content": content})
        used_tokens += cost
    return list(reversed(selected))

