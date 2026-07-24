import sqlite3
import json
import os
from datetime import datetime, timedelta, timezone

DATABASE_FILE = "memory.db"

def get_connection():
    """Get a database connection"""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with required tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Users table for conversation history
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            history TEXT
        )
    """)
    
    # Global log table for channel messages
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS global_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            author TEXT,
            content TEXT
        )
    """)
    
    # Settings table for bot configuration
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Create index on timestamp for faster queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_global_log_timestamp 
        ON global_log(timestamp)
    """)
    
    conn.commit()
    conn.close()

def migrate_from_json(json_file="memory.json"):
    """Migrate existing JSON data to SQLite"""
    if not os.path.exists(json_file):
        print(f"No JSON file found at {json_file}, skipping migration")
        return
    
    try:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"Error reading JSON file: {e}")
        return
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Migrate users
    if "users" in data:
        for user_id, user_data in data["users"].items():
            history_json = json.dumps(user_data.get("history", []))
            cursor.execute("""
                INSERT OR REPLACE INTO users (user_id, username, history)
                VALUES (?, ?, ?)
            """, (user_id, user_data.get("name", ""), history_json))
    
    # Migrate global log
    if "global_log" in data:
        for log_entry in data["global_log"]:
            cursor.execute("""
                INSERT INTO global_log (timestamp, author, content)
                VALUES (?, ?, ?)
            """, (log_entry.get("timestamp", ""), log_entry.get("author", ""), log_entry.get("content", "")))
    
    # Migrate main channel setting
    if "main_channel_id" in data and data["main_channel_id"]:
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES (?, ?)
        """, ("main_channel_id", str(data["main_channel_id"])))
    
    conn.commit()
    conn.close()
    print(f"Successfully migrated data from {json_file} to SQLite")

# User history functions
def get_user_history(user_id):
    """Get conversation history for a user"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT history FROM users WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    
    if row and row["history"]:
        return json.loads(row["history"])
    return []

def save_user_history(user_id, username, history):
    """Save conversation history for a user"""
    conn = get_connection()
    cursor = conn.cursor()
    history_json = json.dumps(history)
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, username, history)
        VALUES (?, ?, ?)
    """, (str(user_id), username, history_json))
    conn.commit()
    conn.close()

# Global log functions
def log_message(author, content):
    """Log a message to the global log"""
    conn = get_connection()
    cursor = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO global_log (timestamp, author, content)
        VALUES (?, ?, ?)
    """, (timestamp, author, content))
    
    # Clean up old messages (older than 48 hours)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    cursor.execute("DELETE FROM global_log WHERE timestamp < ?", (cutoff,))
    
    conn.commit()
    conn.close()

def get_recent_log_text(hours=24, max_lines=100):
    """Get recent log entries as formatted text"""
    conn = get_connection()
    cursor = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    cursor.execute("""
        SELECT timestamp, author, content 
        FROM global_log 
        WHERE timestamp > ? 
        ORDER BY timestamp ASC 
        LIMIT ?
    """, (cutoff, max_lines))
    
    rows = cursor.fetchall()
    conn.close()
    
    return "\n".join(
        f"[{datetime.fromisoformat(row['timestamp']).strftime('%b %d, %H:%M UTC')}] {row['author']}: {row['content']}"
        for row in rows
    )

# Settings functions
def get_setting(key, default=None):
    """Get a setting value"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return row["value"]
    return default

def set_setting(key, value):
    """Set a setting value"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO settings (key, value)
        VALUES (?, ?)
    """, (key, str(value)))
    conn.commit()
    conn.close()

# Convenience functions for main channel
def get_main_channel_id():
    """Get the configured main channel ID"""
    return get_setting("main_channel_id")

def set_main_channel_id(channel_id):
    """Set the main channel ID"""
    set_setting("main_channel_id", str(channel_id))

# Initialize database on import
init_database()

# Check if migration is needed
conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT value FROM settings WHERE key = ?", ("migrated_from_json",))
migrated = cursor.fetchone()
conn.close()

if not migrated and os.path.exists("memory.json"):
    print("Migrating existing JSON data to SQLite...")
    migrate_from_json()
    set_setting("migrated_from_json", "true")
    print("Migration complete!")
