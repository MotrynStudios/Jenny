from __future__ import annotations

import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "trivia_cache.sqlite3"


@contextmanager
def _connect(path=DATABASE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS trivia_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            difficulty TEXT NOT NULL,
            question TEXT NOT NULL UNIQUE,
            answer TEXT NOT NULL,
            evidence TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS trivia_solves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT,
            user_id TEXT NOT NULL,
            question_id INTEGER,
            solve_seconds REAL NOT NULL,
            solved_at TEXT NOT NULL
        )
    """)
    # Keep old solve IDs intact while isolating the new typed questions.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(trivia_questions)")}
    if "fact_key" not in columns:
        connection.execute("BEGIN IMMEDIATE")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(trivia_questions)")}
        if "fact_key" not in columns:
            connection.execute("ALTER TABLE trivia_questions ADD COLUMN fact_key TEXT")
            connection.execute("ALTER TABLE trivia_questions ADD COLUMN category TEXT")
    connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS trivia_source_difficulty
                          ON trivia_questions(category, difficulty, fact_key) WHERE fact_key IS NOT NULL""")
    connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def add_questions(rows: list[dict[str, str]], path=DATABASE_PATH) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect(path) as connection:
        before = connection.total_changes
        connection.executemany(
            "INSERT OR IGNORE INTO trivia_questions(difficulty, question, answer, evidence, created_at, fact_key, category) VALUES(?,?,?,?,?,?,?)",
            [(row["difficulty"], row["question"], row["answer"], row["evidence"], now,
              row["fact_key"], row["category"]) for row in rows],
        )
        return connection.total_changes - before


def bank_questions(category, difficulty, current_facts, path=DATABASE_PATH):
    """Only reuse questions whose source fact is still present in this pack."""
    with _connect(path) as connection:
        rows = connection.execute(
            "SELECT * FROM trivia_questions WHERE category = ? AND difficulty = ?",
            (category, difficulty),
        )
        return [dict(row) for row in rows if row["fact_key"] in current_facts]


def record_solve(guild_id: str | None, user_id: int, question_id: int | None, seconds: float) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO trivia_solves(guild_id,user_id,question_id,solve_seconds,solved_at) VALUES(?,?,?,?,?)",
            (guild_id, str(user_id), question_id, max(0.0, float(seconds)), datetime.now(timezone.utc).isoformat()),
        )


def average_solve_seconds(guild_id: str | None = None) -> float | None:
    with _connect() as connection:
        if guild_id is None:
            value = connection.execute("SELECT AVG(solve_seconds) FROM trivia_solves WHERE guild_id IS NULL").fetchone()[0]
        else:
            value = connection.execute("SELECT AVG(solve_seconds) FROM trivia_solves WHERE guild_id = ?",
                                       (str(guild_id),)).fetchone()[0]
        return float(value) if value is not None else None
