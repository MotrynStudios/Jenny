"""
Shared utility functions and constants for Jenny bot.
Consolidates duplicate code across Jenny-Bot.py and jenny_api_server.py.
"""
import re
from typing import Optional, List, Dict

# Modpack-related keywords for RAG triggering
MODPACK_KEYWORDS: List[str] = [
    "craft", "recipe", "item", "block", "mod", "where find", "how make",
    "enchant", "smelt", "brew", "weapon", "armor", "tool", "biome",
    "dimension", "boss", "mob", "ore", "ingot", "nugget", "plate", "gear",
    "rod", "machine", "generator", "cable", "wire", "minecraft", "modpack",
    "mods", "items", "blocks", "recipes", "bosses", "configs", "config",
    "configuration", "settings", "forge", "fabric",
]
_MODPACK_FOLLOW_UP = re.compile(
    r"\b(?:it|this|that|they|them|those|there|same|what about|how about|does it|"
    r"can it|is it|would it|and then|what if)\b",
    re.IGNORECASE,
)
_SINGING_CUES = re.compile(
    r"(?:[♪♫🎵🎶]|\b(?:sing(?:ing)?|sang|song|lyrics|chorus|la\s+la|na\s+na|doo\s+doo)\b)",
    re.IGNORECASE,
)
_JENNY_WAKE_WORD = re.compile(
    r"\b(?:jenny(?:\s*belle)?|jenni|jennie|jeni|chani|china|shani|sha[a]?ni|jennybell)\b",
    re.IGNORECASE,
)
_JENNY_TEXT_NAME = re.compile(r"\b(?:jenny(?:\s+belle)?|jennybell)\b", re.IGNORECASE)

# Pattern for detecting NEED_SEARCH commands
NEED_SEARCH_PATTERN: re.Pattern = re.compile(r"NEED_SEARCH\s*:\s*(.+)", re.IGNORECASE)

# Fallback reply when AI fails
FALLBACK_REPLY: str = "hm, my brain blanked out on that one, try asking again?"


def is_modpack_related(text: str) -> bool:
    """Match whole modpack terms, avoiding accidental hits like ``mod`` in ``model``."""
    lowered: str = text.lower()
    for keyword in MODPACK_KEYWORDS:
        pattern = r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, lowered):
            return True
    return False


def should_retrieve_modpack_context(text: str, recent_messages: Optional[List[Dict[str, str]]] = None) -> bool:
    """Retrieve pack evidence for direct questions and short, context-dependent follow-ups."""
    if is_modpack_related(text):
        return True
    if not recent_messages or not _MODPACK_FOLLOW_UP.search(text):
        return False

    # Only inspect a few recent user turns so an old modpack topic does not make
    # unrelated conversation retrieve the database indefinitely.
    user_turns = [message.get("content", "") for message in recent_messages if message.get("role") == "user"]
    return any(is_modpack_related(content) for content in user_turns[-3:])


def looks_like_singing(text: str) -> bool:
    """Conservative, local cue check for explicit or strongly repeated singing."""
    if not text:
        return False
    if _SINGING_CUES.search(text):
        return True
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    words = re.findall(r"\b[\w']+\b", normalized)
    if len(words) >= 4 and len(set(words)) <= max(2, len(words) // 3):
        return True
    repeated_phrase = re.search(r"\b((?:\w+\s+){1,4}\w+)\s+\1\b", normalized)
    if repeated_phrase and len(words) >= 6:
        return True
    return False


def contains_jenny_wake_word(text: str) -> bool:
    """Match Jenny and common Whisper misrecognitions without matching substrings."""
    return bool(text and _JENNY_WAKE_WORD.search(text))


def contains_jenny_name(text: str) -> bool:
    """Match Jenny's actual name in text without voice-transcription guesses."""
    return bool(text and _JENNY_TEXT_NAME.search(text))


def extract_search_query(reply: str) -> Optional[str]:
    """Extract search query from NEED_SEARCH command."""
    match: Optional[re.Match] = NEED_SEARCH_PATTERN.search(reply)
    if not match:
        return None
    query: str = match.group(1)
    query = query.splitlines()[0]
    query = re.split(r"NEED_SEARCH\s*:\s*", query, flags=re.IGNORECASE)[0]
    return query.strip().strip('"').strip("'").strip()


def sanitize_final_reply(reply: str) -> str:
    """Sanitize final AI reply for display/TTS."""
    if not reply or not reply.strip():
        return FALLBACK_REPLY
    
    # Remove system commands from output
    if NEED_SEARCH_PATTERN.search(reply):
        # The model got stuck repeating the tag even after search context was given
        return "couldn't quite pin that one down, want me to give it another shot?"
    
    # Clean up multiple newlines
    reply = re.sub(r"\n{3,}", "\n\n", reply)
    
    # Strip whitespace
    reply = reply.strip()
    reply = reply.replace("—", ", ").replace("–", "-")
    
    return reply if reply else FALLBACK_REPLY


def extract_corrected_response(response: str) -> str:
    """
    Extract only the corrected portion when AI self-corrects in a response.
    Detects patterns like "Wait, wrong thing - sorry, let me just say:" and extracts the corrected text.
    """
    if not response:
        return response
    
    response = response.strip()
    
    # Self-correction patterns (case-insensitive)
    correction_patterns = [
        r'wait,\s*wrong\s*thing.*?let\s+me\s+just\s+say:\s*',
        r'actually,\s*i\s+meant:\s*',
        r'let\s+me\s+rephrase\s+that:\s*',
        r'correction:\s*',
        r'on\s+second\s+thought:\s*',
        r'sorry,\s*let\s+me\s+correct\s+that:\s*',
        r'actually,\s*let\s+me\s+just\s+say:\s*',
        r'wait,\s*let\s+me\s+fix\s+that:\s*',
    ]
    
    for pattern in correction_patterns:
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            # Extract everything after the correction pattern
            corrected = response[match.end():].strip()
            if corrected:
                print(f"[FILTER] Detected self-correction pattern, extracting corrected portion")
                return corrected
    
    return response

