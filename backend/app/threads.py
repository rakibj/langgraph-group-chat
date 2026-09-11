"""Lightweight thread index (id, title, strategy, timestamps) alongside the
LangGraph checkpoint DB, so the API can list past conversations — and know
which routing strategy each one uses — without reaching into the
checkpointer's internal schema.
"""

import sqlite3
from datetime import datetime, timezone

from app.graph import DEFAULT_STRATEGY


def init_threads_table(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                thread_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                strategy TEXT NOT NULL DEFAULT 'confidence',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Older DBs created before the strategy column existed.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
        if "strategy" not in columns:
            conn.execute(
                f"ALTER TABLE threads ADD COLUMN strategy TEXT NOT NULL DEFAULT '{DEFAULT_STRATEGY}'"
            )


def touch_thread(db_path: str, thread_id: str, first_message: str, strategy: str) -> None:
    """Insert a thread row (with its strategy) on first message, else just
    bump updated_at — the strategy is fixed at creation and never changes."""
    now = datetime.now(timezone.utc).isoformat()
    title = first_message.strip()[:40] or "New chat"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO threads (thread_id, title, strategy, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (thread_id, title, strategy, now, now),
        )


def get_thread_strategy(db_path: str, thread_id: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT strategy FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        return row[0] if row else None


def list_threads(db_path: str) -> list[dict]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT thread_id, title, strategy, updated_at FROM threads ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]
