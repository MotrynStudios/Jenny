from __future__ import annotations

import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "trivia_cache.sqlite3"


@contextmanager
def _connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
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
    connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def question_count() -> int:
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM trivia_questions").fetchone()[0])


def add_questions(rows: list[dict[str, str]]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        before = connection.total_changes
        connection.executemany(
            "INSERT OR IGNORE INTO trivia_questions(difficulty, question, answer, evidence, created_at) VALUES(?,?,?,?,?)",
            [(row["difficulty"], row["question"], row["answer"], row["evidence"], now) for row in rows],
        )
        return connection.total_changes - before


def get_question_id(question: str) -> int | None:
    """Return the stable cache ID used to associate later solves with a question."""
    with _connect() as connection:
        row = connection.execute("SELECT id FROM trivia_questions WHERE question = ?", (question,)).fetchone()
        return int(row[0]) if row else None


def take_cached_questions(count: int, difficulty: str, exclude: list[str] | None = None) -> list[dict[str, Any]]:
    with _connect() as connection:
        excluded = [str(question) for question in (exclude or [])]
        exclusion_sql = " AND question NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""
        rows = connection.execute(
            "SELECT id, difficulty, question, answer, evidence FROM trivia_questions WHERE difficulty = ?" + exclusion_sql,
            (difficulty, *excluded),
        ).fetchall()
        if len(rows) < count:
            rows = connection.execute(
                "SELECT id, difficulty, question, answer, evidence FROM trivia_questions" +
                (" WHERE question NOT IN (" + ",".join("?" for _ in excluded) + ")" if excluded else ""),
                tuple(excluded),
            ).fetchall()
        selected = random.sample(list(rows), min(count, len(rows)))
        return [dict(row) for row in selected]


def record_solve(guild_id: str | None, user_id: int, question_id: int | None, seconds: float) -> None:
    with _connect() as connection:
        connection.execute(
            "INSERT INTO trivia_solves(guild_id,user_id,question_id,solve_seconds,solved_at) VALUES(?,?,?,?,?)",
            (guild_id, str(user_id), question_id, max(0.0, float(seconds)), datetime.now(timezone.utc).isoformat()),
        )


def average_solve_seconds(guild_id: str | None = None) -> float | None:
    with _connect() as connection:
        if guild_id is None:
            value = connection.execute("SELECT AVG(solve_seconds) FROM trivia_solves").fetchone()[0]
        else:
            value = connection.execute("SELECT AVG(solve_seconds) FROM trivia_solves WHERE guild_id = ?",
                                       (str(guild_id),)).fetchone()[0]
        return float(value) if value is not None else None

