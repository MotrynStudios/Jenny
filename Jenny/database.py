import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

# Anchor the DB file to this script's own folder, not the process's current
# working directory. Previously DATABASE_FILE was just "memory.db", which
# meant running the bot (or any other script that imports this module) from
# a different folder silently created/used a *different* memory.db. This is
# exactly what happened: there were two memory.db files in the toolkit with
# different data in them, depending on where things were launched from.
_SCRIPT_DIR = Path(__file__).resolve().parent
DATABASE_FILE = str(_SCRIPT_DIR / "memory.db")
_GUILD_SETTING_KEYS = {"main_channel_id", "logs_channel_id", "reply_mode", "jenny_enabled"}
_VOICE_LOG_LOCK = threading.RLock()


def get_connection() -> sqlite3.Connection:
    """Get a database connection"""
    conn: sqlite3.Connection = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_database() -> None:
    """Initialize the database with required tables"""
    conn = get_connection()
    cursor = conn.cursor()

    # Users table for conversation history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            history TEXT,
            summary TEXT DEFAULT '',
            last_message_timestamp TEXT DEFAULT ''
        )
    """)

    # Migration for an existing users table created before the `summary`
    # column existed (this is the real memory.db already in use, not just
    # a hypothetical fresh install, so CREATE TABLE IF NOT EXISTS alone
    # won't add it).
    cursor.execute("PRAGMA table_info(users)")
    existing_columns = {row["name"] for row in cursor.fetchall()}
    if "summary" not in existing_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN summary TEXT DEFAULT ''")
    if "last_message_timestamp" not in existing_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_message_timestamp TEXT DEFAULT ''")

    # User profiles table - stores current user data from Discord
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            discriminator TEXT,
            avatar_url TEXT,
            description TEXT,
            pronunciation TEXT,
            joined_discord TEXT,
            joined_server TEXT,
            guild_id TEXT,
            roles TEXT,
            last_updated TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(user_profiles)")
    profile_columns = {row["name"] for row in cursor.fetchall()}
    if "guild_id" not in profile_columns:
        cursor.execute("ALTER TABLE user_profiles ADD COLUMN guild_id TEXT")

    # User profile history table - tracks changes over time
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profile_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            timestamp TEXT,
            guild_id TEXT
        )
    """)
    cursor.execute("PRAGMA table_info(user_profile_history)")
    profile_history_columns = {row["name"] for row in cursor.fetchall()}
    if "guild_id" not in profile_history_columns:
        cursor.execute("ALTER TABLE user_profile_history ADD COLUMN guild_id TEXT")

    # Global log table for channel messages
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            author TEXT,
            user_id TEXT,
            content TEXT,
            channel_id TEXT,
            guild_id TEXT
        )
    """)

    # Apply global_log migrations only after the table exists. Earlier code
    # attempted ALTER TABLE before this CREATE on fresh databases.
    cursor.execute("PRAGMA table_info(global_log)")
    global_log_columns = {row["name"] for row in cursor.fetchall()}
    if "user_id" not in global_log_columns:
        cursor.execute("ALTER TABLE global_log ADD COLUMN user_id TEXT")
    if "channel_id" not in global_log_columns:
        cursor.execute("ALTER TABLE global_log ADD COLUMN channel_id TEXT")
    if "guild_id" not in global_log_columns:
        cursor.execute("ALTER TABLE global_log ADD COLUMN guild_id TEXT")

    # Voice chat table for voice-specific conversations
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS voice_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user_id TEXT,
            username TEXT,
            transcript TEXT,
            response TEXT,
            guild_id TEXT,
            channel_id TEXT,
            timings_json TEXT NOT NULL DEFAULT '{}',
            speech_duration_ms INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("PRAGMA table_info(voice_chat)")
    voice_chat_columns = {row["name"] for row in cursor.fetchall()}
    if "guild_id" not in voice_chat_columns:
        cursor.execute("ALTER TABLE voice_chat ADD COLUMN guild_id TEXT")
    if "channel_id" not in voice_chat_columns:
        cursor.execute("ALTER TABLE voice_chat ADD COLUMN channel_id TEXT")
    if "timings_json" not in voice_chat_columns:
        cursor.execute("ALTER TABLE voice_chat ADD COLUMN timings_json TEXT NOT NULL DEFAULT '{}' ")
    if "speech_duration_ms" not in voice_chat_columns:
        cursor.execute("ALTER TABLE voice_chat ADD COLUMN speech_duration_ms INTEGER NOT NULL DEFAULT 0")

    # Settings table for bot configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Guild configuration is isolated by server. The legacy settings table is
    # retained only for installation-wide defaults during migration.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        )
    """)

    # Conversation turns are scoped so a user's DM, voice conversation, and
    # each server channel do not leak into one another.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_history (
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            history TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (conversation_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scoped_user_memory (
            scope_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            guild_id TEXT,
            model TEXT NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            guild_id TEXT,
            service TEXT NOT NULL,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_service_usage_scope_time ON service_usage(guild_id, user_id, created_at)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_context_cache (
            message_id TEXT PRIMARY KEY,
            guild_id TEXT,
            user_id TEXT NOT NULL,
            channel_id TEXT,
            image_url TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_image_context_user_time ON image_context_cache(guild_id, user_id, created_at)")

    # A member's roles and join date are server-specific. Keep the old table
    # readable for migration, but write new data to the guild-keyed table.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_user_profiles (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            display_name TEXT,
            discriminator TEXT,
            avatar_url TEXT,
            description TEXT,
            pronunciation TEXT,
            joined_discord TEXT,
            joined_server TEXT,
            roles TEXT,
            last_updated TEXT,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    cursor.execute("""
        INSERT OR IGNORE INTO guild_user_profiles
        (guild_id, user_id, username, display_name, discriminator, avatar_url, description,
         pronunciation, joined_discord, joined_server, roles, last_updated)
        SELECT guild_id, user_id, username, display_name, discriminator, avatar_url, description,
               pronunciation, joined_discord, joined_server, roles, last_updated
        FROM user_profiles WHERE guild_id IS NOT NULL
    """)

    # Create indexes for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_global_log_timestamp
        ON global_log(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id
        ON user_profiles(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_profile_history_user_id
        ON user_profile_history(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_profile_history_timestamp
        ON user_profile_history(timestamp)
    """)

    # Channel memory table for long-term channel summaries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_memory (
            channel_id TEXT PRIMARY KEY,
            summary TEXT DEFAULT '',
            last_updated TEXT,
            messages_processed INTEGER DEFAULT 0
        )
    """)

    # Memory maintenance tracking table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_maintenance (
            channel_id TEXT,
            stream_type TEXT,
            last_maintenance_time TEXT,
            last_message_id_processed INTEGER DEFAULT 0,
            messages_since_maintenance INTEGER DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            retry_after TEXT,
            PRIMARY KEY (channel_id, stream_type)
        )
    """)

    # Upgrade the older one-stream maintenance table while preserving its
    # existing counters as the text stream's cursor.
    cursor.execute("PRAGMA table_info(memory_maintenance)")
    maintenance_columns = {row["name"] for row in cursor.fetchall()}
    if "stream_type" not in maintenance_columns:
        cursor.execute("""
            CREATE TABLE memory_maintenance_new (
                channel_id TEXT,
                stream_type TEXT,
                last_maintenance_time TEXT,
                last_message_id_processed INTEGER DEFAULT 0,
                messages_since_maintenance INTEGER DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                retry_after TEXT,
                PRIMARY KEY (channel_id, stream_type)
            )
        """)
        cursor.execute("""
            INSERT INTO memory_maintenance_new
                (channel_id, stream_type, last_maintenance_time, last_message_id_processed, messages_since_maintenance)
            SELECT channel_id, 'text', last_maintenance_time, last_message_id_processed, messages_since_maintenance
            FROM e3.Cursor = conn.cursor()
    cursor.execute("SELECT * FROM channel_memory WHERE channel_id = ?", (str(channel_id),))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


# Memory maintenance tracking functions
def get_memory_maintenance_info(channel_id: str, stream_type: str = "text") -> Dict[str, Any]:
    """Get memory maintenance information for a channel and stream type"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("SELECT * FROM memory_maintenance WHERE channel_id = ? AND stream_type = ?", (str(channel_id), stream_type))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return {
        "channel_id": str(channel_id),
        "stream_type": stream_type,
        "last_maintenance_time": None,
        "last_message_id_processed": 0,
        "messages_since_maintenance": 0,
        "failure_count": 0,
        "retry_after": None,
    }


def update_memory_maintenance(channel_id: str, stream_type: str, last_message_id: int,
                              messages_count: int, reset_pending: bool = False) -> None:
    """Advance a stream cursor while preserving messages received during summarization."""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO memory_maintenance (channel_id, stream_type, last_maintenance_time, last_message_id_processed, messages_since_maintenance)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(channel_id, stream_type) DO UPDATE SET
            last_maintenance_time = excluded.last_maintenance_time,
            last_message_id_processed = excluded.last_message_id_processed,
            failure_count = 0,
            retry_after = NULL,
            messages_since_maintenance = CASE
                WHEN ? THEN 0
                ELSE MAX(0, memory_maintenance.messages_since_maintenance - excluded.messages_since_maintenance)
            END
    """, (str(channel_id), stream_type, timestamp, last_message_id, messages_count, int(reset_pending)))

    conn.commit()
    conn.close()


def defer_memory_maintenance(channel_id: str, stream_type: str) -> datetime:
    """Back off repeated summarization failures to avoid retrying every 15 minutes."""
    conn = get_connection()
    row = conn.execute(
        "SELECT failure_count FROM memory_maintenance WHERE channel_id = ? AND stream_type = ?",
        (str(channel_id), stream_type),
    ).fetchone()
    failure_count = int(row["failure_count"] if row else 0) + 1
    delay_minutes = min(360, 15 * (2 ** min(failure_count - 1, 5)))
    retry_after = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    conn.execute("""
        INSERT INTO memory_maintenance
            (channel_id, stream_type, last_maintenance_time, last_message_id_processed,
             messages_since_maintenance, failure_count, retry_after)
        VALUES (?, ?, ?, 0, 0, ?, ?)
        ON CONFLICT(channel_id, stream_type) DO UPDATE SET
            failure_count = excluded.failure_count,
            retry_after = excluded.retry_after
    """, (str(channel_id), stream_type, datetime.now(timezone.utc).isoformat(),
          failure_count, retry_after.isoformat()))
    conn.commit()
    conn.close()
    return retry_after


def increment_message_count(channel_id: str, stream_type: str = "text") -> None:
    """Increment the message count since last maintenance for a stream type"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO memory_maintenance (channel_id, stream_type, last_maintenance_time, last_message_id_processed, messages_since_maintenance)
        VALUES (?, ?, ?, 0, 1)
        ON CONFLICT(channel_id, stream_type) DO UPDATE SET
            messages_since_maintenance = messages_since_maintenance + 1
    """, (str(channel_id), stream_type, datetime.now(timezone.utc).isoformat()))

    conn.commit()
    conn.close()


def should_trigger_memory_maintenance(channel_id: str, stream_type: str = "text", message_threshold: int = 100, hours_threshold: int = 24) -> bool:
    """Check if memory maintenance should be triggered for a stream type"""
    info = get_memory_maintenance_info(channel_id, stream_type)

    messages_count = info.get("messages_since_maintenance", 0)
    retry_after = info.get("retry_after")
    if retry_after:
        try:
            if datetime.fromisoformat(retry_after) > datetime.now(timezone.utc):
                return False
        except ValueError:
            pass
    last_maintenance = info.get("last_maintenance_time")

    if messages_count <= 0:
        return False

    # Summarize often-used channels at the message threshold. Low-volume
    # channels still get summarized after six hours of accumulated activity.
    if messages_count >= min(message_threshold, 25):
        return True

    # Check time threshold
    if last_maintenance:
        last_time = datetime.fromisoformat(last_maintenance)
        time_diff = datetime.now(timezone.utc) - last_time
        if time_diff.total_seconds() >= min(hours_threshold, 6) * 3600:
            return True
    elif messages_count > 0:
        return True

    return False


def get_messages_for_maintenance(channel_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get messages that need to be processed for memory maintenance"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()

    info = get_memory_maintenance_info(channel_id)
    last_id: int = info.get("last_message_id_processed", 0)

    # CRITICAL FIX: Filter by channel_id to ensure we only get messages from the specific channel
    # The previous implementation was missing this filter, causing cross-channel message retrieval
    cursor.execute("""
        SELECT id, timestamp, author, user_id, content
        FROM global_log
        WHERE id > ? AND channel_id = ? AND author != 'Jenny (System)'
        ORDER BY id ASC
        LIMIT ?
    """, (last_id, channel_id, limit))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "author": row["author"],
            "user_id": row["user_id"],
            "content": row["content"]
        }
        for row in rows
    ]


def get_voice_messages_for_maintenance(guild_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Get voice messages that need to be processed for memory maintenance"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()

    info = get_memory_maintenance_info(guild_id, stream_type="voice")
    last_id: int = info.get("last_message_id_processed", 0)

    cursor.execute("""
        SELECT id, timestamp, user_id, username, transcript, response
        FROM voice_chat
        WHERE id > ? AND guild_id = ?
        ORDER BY id ASC
        LIMIT ?
    """, (last_id, str(guild_id), limit))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "user_id": row["user_id"],
            "username": row["username"],
            "transcript": row["transcript"],
            "response": row["response"]
        }
        for row in rows
    ]


# Changelog functions
def add_changelog_entry(version: str, description: str, features: List[str], changes: List[str], entry_type: str = "release") -> None:
    """Add a changelog entry"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()

    features_json: str = json.dumps(features)
    changes_json: str = json.dumps(changes)

    cursor.execute("""
        INSERT INTO changelog (version, description, features, changes, date, type)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            description = excluded.description,
            features = excluded.features,
            changes = excluded.changes,
            date = excluded.date,
            type = excluded.type
    """, (version, description, features_json, changes_json, timestamp, entry_type))

    conn.commit()
    conn.close()
    print(f"[Changelog] Added entry for version {version}")


def get_changelog() -> List[Dict[str, Any]]:
    """Get all changelog entries"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    
    cursor.execute("""
        SELECT version, description, features, changes, date, type
        FROM changelog
        ORDER BY date DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "version": row["version"],
            "description": row["description"],
            "features": json.loads(row["features"]) if row["features"] else [],
            "changes": json.loads(row["changes"]) if row["changes"] else [],
            "date": row["date"],
            "type": row["type"]
        }
        for row in rows
    ]


# Function to initialize changelog entries (call this after bot is fully started)
def initialize_changelog() -> None:
    """Ensure the current public release entry exists without deleting history."""
    try:
        add_changelog_entry(
            version="0.86",
            description="Jenny 0.86 activity, message routing, pack tools, and diagnostics",
            features=[
                "Conversational chat in the configured main channel, direct messages, and server mentions or replies",
                "Voice conversations with speech recognition, spoken replies, and chat, voice, or both reply modes",
                "Image and animated GIF understanding, plus image context for follow-up conversations",
                "Minecraft mod, modpack, config, and recipe answers grounded in indexed RAG data",
                "External search fallback when local mod data is incomplete, with uncertainty stated clearly",
                "Conversation histories scoped by conversation, shared personal memory across DMs and servers, and automatic channel/voice summaries",
                "Natural language command requests and slash commands for supported bot actions",
                "Server and member information, avatars, roles, join dates, activity windows, and saved profile change history",
                "Role assignment and removal with administrator, role hierarchy, and bot permission checks",
                "Configured channel logging for incoming messages, Jenny replies, and profile events",
                "Voice message attachment transcription in Jenny's configured channel",
                "Chat search and chat summarization for saved messages",
                "Per-user token totals, speech-to-text and text-to-speech duration reports, and paged recent voice timing history",
                "Private help showing commands available to the caller, plus user self-memory controls",
                "Persistent Python, Node, and structured voice-turn logs with bounded retention",
                "Voice service status and clear error replies when a connected feature is unavailable",
                "Configured primary and backup provider fallbacks",
                "Personable concise chat and original playful song responses",
                "Jenny Belle character profile and live speaker/Jenny role metadata in server chat prompts",
                "Minecraft singleplayer 26.3 Playing activity with a restart-resetting elapsed session title",
                "Pack-grounded /mods and interactive /trivia tools, with natural language entry points",
                "Private /health status for Discord, API, voice, RAG corpus, logs channel, and message intent",
                "Three-button changelog pager with a page-jump number button",
            ],
            changes=[
                "Reduced automatic memory summaries to bounded batches, added a smaller retry for malformed output, and added persistent exponential backoff after repeated failures",
                "Restricted summary memory updates to participant IDs and corrected DM memory attribution",
                "Linked personal memory across DMs, server text, and server voice by stable Discord user ID",
                "Updated /mymemory to show cross-context personal memory and /forgetmydata to clear it across all Jenny conversations",
                "Improved NeoForge TOML dependency parsing and safe ChromaDB metadata conversion",
                "Prevented an empty processed corpus from being reported as a successful RAG build",
                "Avoided loading full user profile history unless a profile-related question needs it",
                "Removed an unused prompt argument and duplicate voice-context injection",
                "Preserved prior changelog entries instead of deleting them at startup",
                "Registered the missing on_message Discord event, restoring chat responses and message logging",
                "Added receive-event traces and clear user-visible errors for message processing failures",
                "Verify the selected logs channel by posting a probe before saving it; include slash-command failures in audit logs",
                "Refresh Minecraft activity every 15 seconds using a two-line Playing activity and process uptime",
            ],
            entry_type="release",
        )
        print("[Changelog] Current release entry ensured at version 0.86")
    except Exception as error:
        print(f"[Changelog] Error initializing changelog: {error}")

def get_latest_changelog() -> Optional[Dict[str, Any]]:
    """Get the latest changelog entry"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    
    cursor.execute("""
        SELECT version, description, features, changes, date, type
        FROM changelog
        ORDER BY date DESC
        LIMIT 1
    """)
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "version": row["version"],
            "description": row["description"],
            "features": json.loads(row["features"]) if row["features"] else [],
            "changes": json.loads(row["changes"]) if row["changes"] else [],
            "date": row["date"],
            "type": row["type"]
        }
    return None
