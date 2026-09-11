"""Lightweight thread index (id, title, timestamps) alongside the LangGraph
checkpoint DB, so the API can list past conversations without reaching into
the checkpointer's internal schema.
"""

import sqlite3
from datetime import datetime, timezone


def init_threads_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def touch_thread(db_path: str, thread_id: str, first_message: str) -> None:
    """Insert a thread row on first message, else just bump updated_at."""
    now = datetime.now(timezone.utc).isoformat()
    title = first_message.strip()[:40] or "New chat"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO threads (thread_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (thread_id, title, now, now),
        )


def list_threads(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT thread_id, title, updated_at FROM threads ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
