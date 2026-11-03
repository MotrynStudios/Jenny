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
            FROM memory_maintenance
        """)
        cursor.execute("DROP TABLE memory_maintenance")
        cursor.execute("ALTER TABLE memory_maintenance_new RENAME TO memory_maintenance")

    cursor.execute("PRAGMA table_info(memory_maintenance)")
    maintenance_columns = {row["name"] for row in cursor.fetchall()}
    if "failure_count" not in maintenance_columns:
        cursor.execute("ALTER TABLE memory_maintenance ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0")
    if "retry_after" not in maintenance_columns:
        cursor.execute("ALTER TABLE memory_maintenance ADD COLUMN retry_after TEXT")

    # Changelog table for tracking bot version changes
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS changelog (
            version TEXT PRIMARY KEY,
            description TEXT,
            features TEXT,
            changes TEXT,
            date TEXT,
            type TEXT DEFAULT 'release'
        )
    """)

    # DM text log table for direct messages
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dm_text_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user_id TEXT,
            username TEXT,
            content TEXT,
            direction TEXT,  -- 'incoming' or 'outgoing'
            dm_session_id TEXT  -- Group messages by DM session
        )
    """)

    # DM voice log table for DM voice transcriptions
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dm_voice_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            user_id TEXT,
            username TEXT,
            transcript TEXT,
            response TEXT,
            dm_session_id TEXT
        )
    """)

    # Create indexes for DM tables
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_text_log_timestamp
        ON dm_text_log(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_text_log_user_id
        ON dm_text_log(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_text_log_session
        ON dm_text_log(dm_session_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_voice_log_timestamp
        ON dm_voice_log(timestamp)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_voice_log_user_id
        ON dm_voice_log(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_dm_voice_log_session
        ON dm_voice_log(dm_session_id)
    """)

    conn.commit()
    conn.close()


# User history functions
def get_user_history(user_id: str) -> List[Dict[str, str]]:
    """Get conversation history for a user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("SELECT history FROM users WHERE user_id = ?", (str(user_id),))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()

    if row and row["history"]:
        return json.loads(row["history"])
    return []


def save_user_history(user_id: str, username: str, history: List[Dict[str, str]]) -> None:
    """Save conversation history for a user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    history_json: str = json.dumps(history)
    timestamp: str = datetime.now(timezone.utc).isoformat()
    # ON CONFLICT UPDATE only touches username/history, not summary. Plain
    # "INSERT OR REPLACE" replaces the *entire* row, which would silently
    # reset a user's rolling summary back to empty on every single message
    # since this runs after every reply.
    cursor.execute("""
        INSERT INTO users (user_id, username, history, summary, last_message_timestamp)
        VALUES (?, ?, ?, '', ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username = excluded.username,
            history = excluded.history,
            last_message_timestamp = excluded.last_message_timestamp
    """, (str(user_id), username, history_json, timestamp))
    conn.commit()
    conn.close()


def get_conversation_history(conversation_id: str, user_id: str, limit: int = 24) -> List[Dict[str, str]]:
    """Return the latest turns from one isolated conversation."""
    conn = get_connection()
    row = conn.execute(
        "SELECT history FROM conversation_history WHERE conversation_id = ? AND user_id = ?",
        (str(conversation_id), str(user_id)),
    ).fetchone()
    conn.close()
    if not row or not row["history"]:
        return []
    try:
        history = json.loads(row["history"])
    except (TypeError, json.JSONDecodeError):
        return []
    return history[-limit:]


def save_conversation_history(conversation_id: str, user_id: str, username: str,
                              history: List[Dict[str, str]], limit: int = 24) -> None:
    """Save a bounded conversation window without mixing scopes."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO conversation_history (conversation_id, user_id, username, history, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(conversation_id, user_id) DO UPDATE SET
            username = excluded.username,
            history = excluded.history,
            updated_at = excluded.updated_at
    """, (str(conversation_id), str(user_id), username,
          json.dumps(history[-limit:]), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def clear_conversation_history(conversation_id: str, user_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM conversation_history WHERE conversation_id = ? AND user_id = ?",
                 (str(conversation_id), str(user_id)))
    conn.commit()
    conn.close()


def get_scoped_user_summary(scope_id: str, user_id: str) -> str:
    conn = get_connection()
    row = conn.execute("SELECT summary FROM scoped_user_memory WHERE scope_id = ? AND user_id = ?",
                       (str(scope_id), str(user_id))).fetchone()
    conn.close()
    return row["summary"] if row and row["summary"] else ""


def set_scoped_user_summary(scope_id: str, user_id: str, summary: str) -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO scoped_user_memory (scope_id, user_id, summary, updated_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(scope_id, user_id) DO UPDATE SET summary=excluded.summary, updated_at=excluded.updated_at
    """, (str(scope_id), str(user_id), summary, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_combined_user_summary(user_id: str, scope_id: Optional[str] = None) -> str:
    """Read shared cross-context memory plus the current scope's legacy memory.

    Discord snowflake IDs are stable across DMs and guilds, so the shared
    ``user:<id>`` scope links the same person without relying on mutable names.
    Scope-specific memory remains readable during migration and for older data.
    """
    user_id = str(user_id)
    shared_scope = f"user:{user_id}"
    conn = get_connection()
    rows = conn.execute(
        "SELECT scope_id, summary FROM scoped_user_memory WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    legacy_row = conn.execute("SELECT summary FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    summaries = {str(row["scope_id"]): str(row["summary"] or "").strip() for row in rows}
    # Older releases stored a per-user summary in users.summary. Continue to
    # expose it until the next maintenance pass writes the canonical shared row.
    shared = summaries.get(shared_scope, "") or (str(legacy_row["summary"] or "").strip() if legacy_row else "")
    current_scope = str(scope_id) if scope_id else None

    if shared:
        # Once the shared record exists, read it plus only the active scope.
        # This avoids adding stale copies from every old guild/DM scope.
        current_local = summaries.get(current_scope, "") if current_scope else ""
        local_summaries = [] if current_local == shared else [current_local]
    else:
        # Before the first shared summary is written, bridge legacy memories
        # from any prior DM or guild scope so context is available immediately.
        local_summaries = [value for key, value in summaries.items() if key != shared_scope]

    sections = []
    if shared:
        sections.append(f"Shared memory across Jenny conversations:\n{shared}")
    for local in dict.fromkeys(value for value in local_summaries if value):
        sections.append(f"Memory from this server or DM:\n{local}")
    return "\n\n".join(sections)


def clear_user_conversations(user_id: str, guild_id: Optional[str] = None,
                             dm_only: bool = False) -> None:
    conn = get_connection()
    if dm_only:
        dm_conversation = f"dm:{user_id}"
        dm_scope = f"dm:{user_id}"
        conn.execute("DELETE FROM conversation_history WHERE user_id = ? AND conversation_id = ?",
                     (str(user_id), dm_conversation))
        conn.execute("DELETE FROM scoped_user_memory WHERE user_id = ? AND scope_id = ?",
                     (str(user_id), dm_scope))
    elif guild_id is None:
        conn.execute("DELETE FROM conversation_history WHERE user_id = ?", (str(user_id),))
        conn.execute("DELETE FROM scoped_user_memory WHERE user_id = ?", (str(user_id),))
        conn.execute("DELETE FROM users WHERE user_id = ?", (str(user_id),))
    else:
        guild_scope = f"guild:{guild_id}"
        conn.execute(
            "DELETE FROM conversation_history WHERE user_id = ? AND (conversation_id LIKE ? OR conversation_id LIKE ?)",
            (str(user_id), f"guild:{guild_id}:%", f"voice:{guild_id}:%"),
        )
        conn.execute("DELETE FROM scoped_user_memory WHERE user_id = ? AND scope_id = ?",
                     (str(user_id), guild_scope))
    conn.commit()
    conn.close()


def record_token_usage(user_id: str, guild_id: Optional[str], model: str,
                       prompt_tokens: int, completion_tokens: int, total_tokens: int) -> None:
    conn = get_connection()
    conn.execute("""
        INSERT INTO token_usage (user_id, guild_id, model, prompt_tokens, completion_tokens, total_tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(user_id), str(guild_id) if guild_id else None, model,
          int(prompt_tokens or 0), int(completion_tokens or 0), int(total_tokens or 0),
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_token_usage(guild_id: Optional[str], user_id: Optional[str] = None,
                    since: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    clauses, params = [], []
    if guild_id is not None:
        clauses.append("guild_id = ?")
        params.append(str(guild_id))
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(str(user_id))
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(f"""
        SELECT user_id, guild_id, SUM(prompt_tokens) AS prompt_tokens,
               SUM(completion_tokens) AS completion_tokens, SUM(total_tokens) AS total_tokens,
               COUNT(*) AS requests
        FROM token_usage{where}
        GROUP BY user_id, guild_id
        ORDER BY total_tokens DESC LIMIT ?
    """, (*params, int(limit))).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def record_service_usage(user_id: Optional[str], guild_id: Optional[str], service: str,
                         duration_ms: int) -> None:
    """Record usage duration for speech recognition or speech synthesis."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO service_usage (user_id, guild_id, service, duration_ms, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(user_id) if user_id else None, str(guild_id) if guild_id else None,
         str(service).lower(), max(0, int(duration_ms or 0)), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def get_service_usage(guild_id: Optional[str], user_id: Optional[str] = None,
                      since: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    clauses, params = [], []
    if guild_id is not None:
        clauses.append("guild_id = ?")
        params.append(str(guild_id))
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(str(user_id))
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT user_id, service, SUM(duration_ms) AS duration_ms, COUNT(*) AS requests "
        f"FROM service_usage{where} GROUP BY user_id, service ORDER BY duration_ms DESC",
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_server_activity_stats(guild_id: str, since: str,
                              user_id: Optional[str] = None) -> Dict[str, int]:
    """Return saved message and voice activity counts for a guild/time window."""
    conn = get_connection()
    message_sql = "SELECT COUNT(*) FROM global_log WHERE guild_id = ? AND timestamp >= ? AND author != 'Jenny (System)'"
    message_params: List[Any] = [str(guild_id), since]
    voice_sql = "SELECT COUNT(*), COALESCE(SUM(speech_duration_ms), 0) FROM voice_chat WHERE guild_id = ? AND timestamp >= ?"
    voice_params: List[Any] = [str(guild_id), since]
    if user_id is not None:
        message_sql += " AND user_id = ?"
        message_params.append(str(user_id))
        voice_sql += " AND user_id = ?"
        voice_params.append(str(user_id))
    message_count = int(conn.execute(message_sql, message_params).fetchone()[0])
    voice_row = conn.execute(voice_sql, voice_params).fetchone()
    conn.close()
    return {"messages": message_count, "voice_inputs": int(voice_row[0]),
            "voice_duration_ms": int(voice_row[1])}


def append_voice_turn_log(entry: Dict[str, Any]) -> None:
    """Append one completed voice turn as JSONL for transparent diagnostics."""
    log_dir = _SCRIPT_DIR.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "voice-turns.jsonl"
    with _VOICE_LOG_LOCK, path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def cleanup_expired_records(retention_days: int = 90) -> Dict[str, int]:
    """Prune detailed chat, voice, token, and speech records beyond retention."""
    days = max(7, min(int(retention_days), 3650))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_connection()
    tables = {
        "global_log": "timestamp",
        "voice_chat": "timestamp",
        "token_usage": "created_at",
        "service_usage": "created_at",
        "dm_text_log": "timestamp",
        "dm_voice_log": "timestamp",
        "user_profile_history": "timestamp",
        "conversation_history": "updated_at",
    }
    deleted: Dict[str, int] = {}
    for table, column in tables.items():
        cursor = conn.execute(f"DELETE FROM {table} WHERE {column} < ?", (cutoff,))
        deleted[table] = max(0, cursor.rowcount)
    # This legacy raw-history column is no longer read by the current bot.
    legacy_cursor = conn.execute(
        "UPDATE users SET history = '[]' WHERE last_message_timestamp < ? AND history IS NOT NULL AND history != '[]'",
        (cutoff,),
    )
    deleted["legacy_user_history_cleared"] = max(0, legacy_cursor.rowcount)
    conn.execute("DELETE FROM image_context_cache WHERE created_at < ?", (cutoff,))
    deleted["image_context_cache"] = max(0, conn.execute("SELECT changes()").fetchone()[0])
    conn.commit()
    conn.close()

    voice_log = _SCRIPT_DIR.parent / "logs" / "voice-turns.jsonl"
    if voice_log.exists():
        with _VOICE_LOG_LOCK:
            retained_lines = []
            try:
                for line in voice_log.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                        if str(record.get("timestamp", "")) >= cutoff:
                            retained_lines.append(json.dumps(record, ensure_ascii=False))
                    except json.JSONDecodeError:
                        continue
                temporary_log = voice_log.with_suffix(".jsonl.tmp")
                temporary_log.write_text("\n".join(retained_lines) + ("\n" if retained_lines else ""), encoding="utf-8")
                temporary_log.replace(voice_log)
            except OSError:
                pass
    return deleted


def save_image_context(message_id: str, guild_id: Optional[str], user_id: str,
                       channel_id: Optional[str], image_url: str, description: str) -> None:
    conn = get_connection()
    stale_before = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conn.execute("DELETE FROM image_context_cache WHERE created_at < ?", (stale_before,))
    conn.execute("""
        INSERT OR REPLACE INTO image_context_cache
        (message_id, guild_id, user_id, channel_id, image_url, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(message_id), str(guild_id) if guild_id else None, str(user_id),
          str(channel_id) if channel_id else None, image_url, description,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_latest_image_context(guild_id: Optional[str], user_id: str,
                             max_age_hours: int = 24) -> Optional[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    conn = get_connection()
    row = conn.execute("""
        SELECT message_id, guild_id, user_id, channel_id, image_url, description, created_at
        FROM image_context_cache
        WHERE guild_id IS ? AND user_id = ? AND created_at >= ?
        ORDER BY created_at DESC LIMIT 1
    """, (str(guild_id) if guild_id else None, str(user_id), cutoff)).fetchone()
    conn.close()
    return dict(row) if row else None


# Rolling summary functions (long-term memory beyond the raw history window)
def get_user_summary(user_id: str) -> str:
    """Get the rolling summary of older conversation with a user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("SELECT summary FROM users WHERE user_id = ?", (str(user_id),))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()

    if row and row["summary"]:
        return row["summary"]
    return ""


def set_user_summary(user_id: str, summary: str) -> None:
    """Update the rolling summary for a user (row must already exist,
    save_user_history creates it on the first message)"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("UPDATE users SET summary = ? WHERE user_id = ?", (summary, str(user_id)))
    conn.commit()
    conn.close()


def get_last_message_timestamp(user_id: str) -> Optional[str]:
    """Get the timestamp of the last message from a user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("SELECT last_message_timestamp FROM users WHERE user_id = ?", (str(user_id),))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()

    if row and row["last_message_timestamp"]:
        return row["last_message_timestamp"]
    return None


def update_last_message_timestamp(user_id: str) -> None:
    """Update the last message timestamp for a user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO users (user_id, last_message_timestamp)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            last_message_timestamp = excluded.last_message_timestamp
    """, (str(user_id), timestamp))
    conn.commit()
    conn.close()


# Global log functions
def log_message(author: str, content: str, user_id: Optional[str] = None,
                channel_id: Optional[str] = None, guild_id: Optional[str] = None) -> Optional[int]:
    """Log a message to the global log"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO global_log (timestamp, author, user_id, content, channel_id, guild_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (timestamp, author, str(user_id) if user_id else None, content,
          str(channel_id) if channel_id else None, str(guild_id) if guild_id else None))

    conn.commit()

    # Get the message ID that was just inserted
    message_id: Optional[int] = cursor.lastrowid

    conn.close()

    # Internal maintenance notes are diagnostic records, not conversation turns.
    if channel_id and author != "Jenny (System)":
        increment_message_count(channel_id)

    return message_id


def log_voice_chat(user_id: str, username: str, transcript: str, response: str,
                   guild_id: str, channel_id: Optional[str] = None,
                   timings_ms: Optional[Dict[str, int]] = None,
                   speech_duration_ms: int = 0) -> None:
    """Log a voice chat interaction to the voice_chat table"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO voice_chat
            (timestamp, user_id, username, transcript, response, guild_id, channel_id, timings_json, speech_duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (timestamp, str(user_id), username, transcript, response, str(guild_id),
          str(channel_id) if channel_id else None, json.dumps(timings_ms or {}),
          max(0, int(speech_duration_ms or 0))))

    conn.commit()
    conn.close()


def update_voice_chat_response(user_id: str, guild_id: str, transcript: str, response: str,
                               timings_ms: Optional[Dict[str, int]] = None,
                               speech_duration_ms: Optional[int] = None) -> None:
    """Fill the response for the just-recorded voice turn without duplicating it."""
    conn = get_connection()
    row = conn.execute("""
        SELECT id, timings_json, speech_duration_ms FROM voice_chat
        WHERE user_id = ? AND guild_id = ? AND transcript = ? ORDER BY id DESC LIMIT 1
    """, (str(user_id), str(guild_id), transcript)).fetchone()
    if row:
        try:
            merged_timings = json.loads(row["timings_json"] or "{}")
        except json.JSONDecodeError:
            merged_timings = {}
        merged_timings.update(timings_ms or {})
        conn.execute("""
            UPDATE voice_chat SET response = ?, timings_json = ?, speech_duration_ms = ? WHERE id = ?
        """, (response, json.dumps(merged_timings),
              max(0, int(speech_duration_ms)) if speech_duration_ms is not None else row["speech_duration_ms"],
              row["id"]))
    conn.commit()
    conn.close()


def update_voice_chat_timings(user_id: str, guild_id: str, transcript: str,
                              timings_ms: Dict[str, int]) -> None:
    """Merge late pipeline timings such as TTS into the latest matching turn."""
    conn = get_connection()
    row = conn.execute("""
        SELECT id, timings_json FROM voice_chat
        WHERE user_id = ? AND guild_id = ? AND transcript = ? ORDER BY id DESC LIMIT 1
    """, (str(user_id), str(guild_id), transcript)).fetchone()
    if row:
        try:
            timings = json.loads(row["timings_json"] or "{}")
        except json.JSONDecodeError:
            timings = {}
        timings.update({key: max(0, int(value or 0)) for key, value in timings_ms.items()})
        conn.execute("UPDATE voice_chat SET timings_json = ? WHERE id = ?",
                     (json.dumps(timings), row["id"]))
    conn.commit()
    conn.close()


def get_dm_sessions() -> List[str]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT dm_session_id FROM dm_text_log WHERE dm_session_id IS NOT NULL
        UNION SELECT dm_session_id FROM dm_voice_log WHERE dm_session_id IS NOT NULL
    """).fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_dm_text_for_maintenance(session_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, timestamp, user_id, username, content, direction
        FROM dm_text_log WHERE dm_session_id = ? AND id > ? ORDER BY id ASC LIMIT ?
    """, (session_id, after_id, limit)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_dm_voice_for_maintenance(session_id: str, after_id: int = 0, limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, timestamp, user_id, username, transcript, response
        FROM dm_voice_log WHERE dm_session_id = ? AND id > ? ORDER BY id ASC LIMIT ?
    """, (session_id, after_id, limit)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def search_chat_messages(channel_id: str, query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search only the configured Discord channel's stored message log."""
    conn = get_connection()
    pattern = f"%{query}%"
    rows = conn.execute("""
        SELECT timestamp, author, user_id, content FROM global_log
        WHERE channel_id = ? AND content LIKE ? ORDER BY id DESC LIMIT ?
    """, (str(channel_id), pattern, max(1, min(int(limit), 25)))).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_recent_channel_messages(channel_id: str, hours: int = 24, limit: int = 150) -> List[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(int(hours), 720)))).isoformat()
    conn = get_connection()
    rows = conn.execute("""
        SELECT timestamp, author, user_id, content FROM global_log
        WHERE channel_id = ? AND timestamp >= ? ORDER BY id DESC LIMIT ?
    """, (str(channel_id), cutoff, max(1, min(int(limit), 500)))).fetchall()
    conn.close()
    return [dict(row) for row in reversed(rows)]


def get_last_user_message(guild_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    row = conn.execute("""
        SELECT timestamp, channel_id, content FROM global_log
        WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1
    """, (str(guild_id), str(user_id))).fetchone()
    conn.close()
    return dict(row) if row else None


# DM logging functions
def log_dm_text(user_id: str, username: str, content: str, direction: str, dm_session_id: str = None) -> Optional[int]:
    """Log a DM text message to the dm_text_log table"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()

    # Generate session ID if not provided (group messages by user)
    if dm_session_id is None:
        dm_session_id = f"dm_{user_id}"

    cursor.execute("""
        INSERT INTO dm_text_log (timestamp, user_id, username, content, direction, dm_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (timestamp, str(user_id), username, content, direction, dm_session_id))

    conn.commit()

    # Get the message ID that was just inserted
    message_id: Optional[int] = cursor.lastrowid

    conn.close()

    # Increment message count for DM memory maintenance
    increment_message_count(dm_session_id, stream_type="dm_text")

    return message_id


def log_dm_voice(user_id: str, username: str, transcript: str, response: str, dm_session_id: str = None) -> None:
    """Log a DM voice chat interaction to the dm_voice_log table"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()

    # Generate session ID if not provided
    if dm_session_id is None:
        dm_session_id = f"dm_{user_id}"

    cursor.execute("""
        INSERT INTO dm_voice_log (timestamp, user_id, username, transcript, response, dm_session_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (timestamp, str(user_id), username, transcript, response, dm_session_id))

    conn.commit()
    conn.close()

    # Increment message count for DM memory maintenance
    increment_message_count(dm_session_id, stream_type="dm_voice")


def get_recent_dm_text(hours: int = 24, max_entries: int = 50, user_id: str = None) -> List[Dict[str, str]]:
    """Get recent DM text entries, optionally filtered by user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cutoff: str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if user_id:
        cursor.execute("""
            SELECT timestamp, user_id, username, content, direction, dm_session_id
            FROM dm_text_log
            WHERE timestamp > ? AND user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, str(user_id), max_entries))
    else:
        cursor.execute("""
            SELECT timestamp, user_id, username, content, direction, dm_session_id
            FROM dm_text_log
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, max_entries))

    rows: List[sqlite3.Row] = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_recent_dm_voice(hours: int = 24, max_entries: int = 50, user_id: str = None) -> List[Dict[str, str]]:
    """Get recent DM voice entries, optionally filtered by user"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cutoff: str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if user_id:
        cursor.execute("""
            SELECT timestamp, user_id, username, transcript, response, dm_session_id
            FROM dm_voice_log
            WHERE timestamp > ? AND user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, str(user_id), max_entries))
    else:
        cursor.execute("""
            SELECT timestamp, user_id, username, transcript, response, dm_session_id
            FROM dm_voice_log
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff, max_entries))

    rows: List[sqlite3.Row] = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_recent_voice_chat(hours: int = 1, max_entries: int = 50,
                          guild_id: Optional[str] = None,
                          user_id: Optional[str] = None,
                          channel_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Get recent voice chat entries"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cutoff: str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if channel_id is not None:
        cursor.execute("""
        SELECT timestamp, user_id, username, transcript, response, guild_id, channel_id, timings_json, speech_duration_ms
        FROM voice_chat
        WHERE timestamp > ? AND guild_id IS ? AND channel_id = ?
        ORDER BY timestamp DESC LIMIT ?
        """, (cutoff, str(guild_id) if guild_id else None, str(channel_id), max_entries))
    elif guild_id is None and user_id is None:
        cursor.execute("""
        SELECT timestamp, user_id, username, transcript, response, guild_id, channel_id, timings_json, speech_duration_ms
        FROM voice_chat
        WHERE timestamp > ?
        ORDER BY timestamp DESC
        LIMIT ?
        """, (cutoff, max_entries))
    elif user_id is None:
        cursor.execute("""
            SELECT timestamp, user_id, username, transcript, response, guild_id, channel_id, timings_json, speech_duration_ms
            FROM voice_chat WHERE timestamp > ? AND guild_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (cutoff, str(guild_id), max_entries))
    else:
        cursor.execute("""
            SELECT timestamp, user_id, username, transcript, response, guild_id, channel_id, timings_json, speech_duration_ms
            FROM voice_chat WHERE timestamp > ? AND guild_id IS ? AND user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (cutoff, str(guild_id) if guild_id else None, str(user_id), max_entries))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "timestamp": row["timestamp"],
            "user_id": row["user_id"],
            "username": row["username"],
            "transcript": row["transcript"],
            "response": row["response"],
            "guild_id": row["guild_id"],
            "channel_id": row["channel_id"],
            "timings_ms": json.loads(row["timings_json"] or "{}"),
            "speech_duration_ms": int(row["speech_duration_ms"] or 0)
        }
        for row in rows
    ]


def get_recent_user_messages(guild_id: Optional[str], user_id: str,
                             hours: int = 24, limit: int = 10) -> List[Dict[str, str]]:
    """Fetch a user's own recent messages for cross-channel and cross-modal context."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = get_connection()
    rows = conn.execute("""
        SELECT timestamp, author, content, channel_id FROM global_log
        WHERE guild_id IS ? AND user_id = ? AND timestamp >= ?
        ORDER BY id DESC LIMIT ?
    """, (str(guild_id) if guild_id else None, str(user_id), cutoff, max(1, min(limit, 30)))).fetchall()
    conn.close()
    return [dict(row) for row in reversed(rows)]


def get_recent_log_text(hours: int = 24, max_lines: int = 100, guild_id: Optional[str] = None) -> str:
    """Get recent log entries as formatted text"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cutoff: str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    if guild_id is None:
        cursor.execute("""
            SELECT timestamp, author, content FROM global_log
            WHERE timestamp > ? ORDER BY timestamp ASC LIMIT ?
        """, (cutoff, max_lines))
    else:
        cursor.execute("""
            SELECT timestamp, author, content FROM global_log
            WHERE timestamp > ? AND guild_id = ? ORDER BY timestamp ASC LIMIT ?
        """, (cutoff, str(guild_id), max_lines))

    rows = cursor.fetchall()
    conn.close()

    return "\n".join(
        f"[{datetime.fromisoformat(row['timestamp']).strftime('%b %d, %H:%M UTC')}] {row['author']}: {row['content']}"
        for row in rows
    )


# Settings functions
def get_setting(key: str, default: Optional[str] = None, guild_id: Optional[str] = None) -> Optional[str]:
    """Get a setting value"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    if guild_id is not None:
        cursor.execute("SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?", (str(guild_id), key))
        row = cursor.fetchone()
        if row:
            conn.close()
            return row["value"]
        if key in _GUILD_SETTING_KEYS:
            conn.close()
            return default
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()

    if row:
        return row["value"]
    return default


def set_setting(key: str, value: str, guild_id: Optional[str] = None) -> None:
    """Set a setting value"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    if guild_id is None:
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        """, (key, str(value)))
    else:
        cursor.execute("""
            INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value
        """, (str(guild_id), key, str(value)))
    conn.commit()
    conn.close()


# Convenience functions for main channel
def get_main_channel_id(guild_id: Optional[str] = None) -> Optional[str]:
    """Get the configured main channel ID"""
    return get_setting("main_channel_id", guild_id=guild_id)


def set_main_channel_id(channel_id: str, guild_id: Optional[str] = None) -> None:
    """Set the main channel ID"""
    set_setting("main_channel_id", str(channel_id), guild_id=guild_id)


# Convenience functions for logs channel
def get_logs_channel_id(guild_id: Optional[str] = None) -> Optional[str]:
    """Get the configured logs channel ID"""
    return get_setting("logs_channel_id", guild_id=guild_id)


def set_logs_channel_id(channel_id: str, guild_id: Optional[str] = None) -> None:
    """Set the logs channel ID"""
    set_setting("logs_channel_id", str(channel_id), guild_id=guild_id)


# Initialize database on import
init_database()


# User profile functions
def save_user_profile(user_id: str, username: str, display_name: str, discriminator: Optional[str], avatar_url: Optional[str], 
                      description: Optional[str], pronunciation: Optional[str], joined_discord: Optional[str], joined_server: Optional[str], 
                      guild_id: str, roles: Optional[List[str]]) -> None:
    """Save or update a user's profile data"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    
    # Get existing profile to check for changes
    cursor.execute("SELECT * FROM guild_user_profiles WHERE guild_id = ? AND user_id = ?",
                   (str(guild_id), str(user_id)))
    existing: Optional[sqlite3.Row] = cursor.fetchone()
    
    timestamp: str = datetime.now(timezone.utc).isoformat()
    roles_json: Optional[str] = json.dumps(roles) if roles else None
    
    if existing:
        # Check for changes and log them
        fields_to_check = [
            ('username', username),
            ('display_name', display_name),
            ('discriminator', discriminator),
            ('avatar_url', avatar_url),
            ('description', description),
            ('pronunciation', pronunciation),
            ('roles', roles_json)
        ]
        
        for field_name, new_value in fields_to_check:
            old_value = existing[field_name] if field_name in existing.keys() else None
            if old_value != new_value:
                # Log the change
                cursor.execute("""
                    INSERT INTO user_profile_history (user_id, field_name, old_value, new_value, timestamp, guild_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (str(user_id), field_name, old_value, new_value, timestamp, str(guild_id)))
        
        # Update the profile
        cursor.execute("""
            INSERT INTO guild_user_profiles
                (guild_id, user_id, username, display_name, discriminator, avatar_url,
                 description, pronunciation, joined_discord, joined_server, roles, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                username=excluded.username, display_name=excluded.display_name,
                discriminator=excluded.discriminator, avatar_url=excluded.avatar_url,
                description=excluded.description, pronunciation=excluded.pronunciation,
                joined_discord=excluded.joined_discord, joined_server=excluded.joined_server,
                roles=excluded.roles, last_updated=excluded.last_updated
        """, (str(guild_id), str(user_id), username, display_name, discriminator, avatar_url,
              description, pronunciation, joined_discord, joined_server, roles_json, timestamp))
    else:
        # Insert new profile
        cursor.execute("""
            INSERT INTO guild_user_profiles
            (guild_id, user_id, username, display_name, discriminator, avatar_url, description,
             pronunciation, joined_discord, joined_server, roles, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(guild_id), str(user_id), username, display_name, discriminator, avatar_url,
              description, pronunciation, joined_discord, joined_server, roles_json, timestamp))
    
    conn.commit()
    conn.close()


def get_user_profile(user_id: str, guild_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get a user's current profile data"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    if guild_id is None:
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = ?", (str(user_id),))
    else:
        cursor.execute("SELECT * FROM guild_user_profiles WHERE user_id = ? AND guild_id = ?",
                       (str(user_id), str(guild_id)))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    return None


def get_user_profile_history(user_id: str, limit: int = 50, guild_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Get a user's profile change history"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    if guild_id is None:
        cursor.execute("""
        SELECT field_name, old_value, new_value, timestamp
        FROM user_profile_history
        WHERE user_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """, (str(user_id), limit))
    else:
        cursor.execute("""
            SELECT field_name, old_value, new_value, timestamp
            FROM user_profile_history WHERE user_id = ? AND guild_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (str(user_id), str(guild_id), limit))
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "field_name": row["field_name"],
            "old_value": row["old_value"],
            "new_value": row["new_value"],
            "timestamp": row["timestamp"]
        }
        for row in rows
    ]


def get_all_user_profiles(guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all user profiles, optionally filtered by guild"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    
    if guild_id:
        cursor.execute("SELECT * FROM guild_user_profiles WHERE guild_id = ?", (str(guild_id),))
    else:
        cursor.execute("SELECT * FROM guild_user_profiles")
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_recent_profile_changes(hours: int = 24, limit: int = 100,
                               guild_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Get recent profile changes across all users"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cutoff: str = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    cursor.execute("""
        SELECT user_id, field_name, old_value, new_value, timestamp, guild_id
        FROM user_profile_history
        WHERE timestamp > ? AND (? IS NULL OR guild_id = ?)
        ORDER BY timestamp DESC
        LIMIT ?
    """, (cutoff, str(guild_id) if guild_id else None, str(guild_id) if guild_id else None, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "user_id": row["user_id"],
            "field_name": row["field_name"],
            "old_value": row["old_value"],
            "new_value": row["new_value"],
            "timestamp": row["timestamp"],
            "guild_id": row["guild_id"]
        }
        for row in rows
    ]


def find_user_by_name(search_name: str, guild_id: Optional[str] = None) -> List[Dict[str, str]]:
    """Find users by name (username or display name)"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    
    search_pattern: str = f"%{search_name}%"
    
    if guild_id:
        cursor.execute("""
            SELECT user_id, username, display_name, discriminator, avatar_url
            FROM guild_user_profiles
            WHERE (username LIKE ? OR display_name LIKE ?)
            AND guild_id = ?
            LIMIT 10
        """, (search_pattern, search_pattern, str(guild_id)))
    else:
        cursor.execute("""
            SELECT user_id, username, display_name, discriminator, avatar_url
            FROM guild_user_profiles
            WHERE username LIKE ? OR display_name LIKE ?
            LIMIT 10
        """, (search_pattern, search_pattern))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "user_id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "discriminator": row["discriminator"],
            "avatar_url": row["avatar_url"]
        }
        for row in rows
    ]


def format_user_profile_for_context(user_id: str, guild_id: Optional[str] = None) -> Optional[str]:
    """Format user profile data for AI context"""
    profile = get_user_profile(user_id, guild_id)
    if not profile:
        return None
    
    context = f"User Profile for {profile.get('display_name', profile.get('username', 'Unknown'))}:\n"
    context += f"- Display Name: {profile.get('display_name', 'N/A')}\n"
    context += f"- Username: {profile.get('username', 'N/A')}\n"
    
    if profile.get('roles'):
        try:
            import json
            roles = json.loads(profile['roles'])
            context += f"- Roles: {', '.join(roles)}\n"
        except:
            context += f"- Roles: {profile['roles']}\n"
    
    if profile.get('joined_server'):
        context += f"- Joined Server: {profile['joined_server']}\n"
    
    if profile.get('joined_discord'):
        context += f"- Joined Discord: {profile['joined_discord']}\n"
    
    # Add recent changes
    history = get_user_profile_history(user_id, limit=5, guild_id=guild_id)
    if history:
        context += "- Recent Changes:\n"
        for change in history:
            context += f"  * {change['field_name']}: {change['old_value'] or 'None'} → {change['new_value'] or 'None'} ({change['timestamp']})\n"
    
    return context


# Channel memory functions
def get_channel_memory(channel_id: str) -> str:
    """Get the long-term memory summary for a channel"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    cursor.execute("SELECT summary FROM channel_memory WHERE channel_id = ?", (str(channel_id),))
    row: Optional[sqlite3.Row] = cursor.fetchone()
    conn.close()
    
    if row and row["summary"]:
        return row["summary"]
    return ""


def set_channel_memory(channel_id: str, summary: str) -> None:
    """Update the long-term memory summary for a channel"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
    timestamp: str = datetime.now(timezone.utc).isoformat()
    
    cursor.execute("""
        INSERT INTO channel_memory (channel_id, summary, last_updated, messages_processed)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(channel_id) DO UPDATE SET
            summary = excluded.summary,
            last_updated = excluded.last_updated,
            messages_processed = messages_processed + 1
    """, (str(channel_id), summary, timestamp))
    
    conn.commit()
    conn.close()


def get_channel_memory_stats(channel_id: str) -> Optional[Dict[str, Any]]:
    """Get statistics about channel memory"""
    conn: sqlite3.Connection = get_connection()
    cursor: sqlite3.Cursor = conn.cursor()
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
            version="0.84",
            description="Jenny 0.84 character, server role context, and live activity",
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
                "Minecraft singleplayer 26.3 Playing activity with a restart-resetting elapsed session title"
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
                "Preserved prior changelog entries instead of deleting them at startup"
            ],
            entry_type="release",
        )
        print("[Changelog] Current release entry ensured at version 0.84")
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
