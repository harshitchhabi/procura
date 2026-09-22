"""SQLite persistence layer for Procura.

Deliberately raw sqlite3 (stdlib only, no ORM) to keep the project lightweight
and transparent -- every query is visible and easy to reason about for a
portfolio / academic review.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

DB_PATH = Path(__file__).parent / "procura.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor() -> Iterator[sqlite3.Cursor]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS processes (
    pid INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'Medium',
    deadline TEXT,
    burst_time INTEGER NOT NULL,
    arrival_time TEXT NOT NULL,
    memory_requirement INTEGER NOT NULL DEFAULT 0,
    cpu_requirement INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'NEW',
    error_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ready_since TEXT
);

CREATE TABLE IF NOT EXISTS errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid INTEGER REFERENCES processes(pid) ON DELETE CASCADE,
    error_type TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    raw_details TEXT
);

CREATE TABLE IF NOT EXISTS diagnoses (
    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id INTEGER REFERENCES errors(error_id) ON DELETE CASCADE,
    diagnosis_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS recovery_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_id INTEGER REFERENCES errors(error_id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    target_pid INTEGER REFERENCES processes(pid) ON DELETE SET NULL,
    executed_at TEXT NOT NULL
);
"""


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    """Drop and recreate all tables. Used by tests and seed_data.py."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS recovery_actions;
            DROP TABLE IF EXISTS diagnoses;
            DROP TABLE IF EXISTS errors;
            DROP TABLE IF EXISTS processes;
            """
        )
        conn.commit()
    finally:
        conn.close()
    init_db()


# ---------------------------------------------------------------------------
# Process CRUD
# ---------------------------------------------------------------------------

def create_process(
    name: str,
    description: str = "",
    priority: str = "Medium",
    deadline: Optional[str] = None,
    burst_time: int = 10,
    memory_requirement: int = 0,
    cpu_requirement: int = 0,
    arrival_time: Optional[str] = None,
) -> dict[str, Any]:
    arrival = arrival_time or now_iso()
    created = now_iso()
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO processes
                (name, description, priority, deadline, burst_time, arrival_time,
                 memory_requirement, cpu_requirement, state, error_count, created_at, ready_since)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'NEW', 0, ?, NULL)
            """,
            (name, description, priority, deadline, burst_time, arrival,
             memory_requirement, cpu_requirement, created),
        )
        pid = cur.lastrowid
    return get_process(pid)


def get_process(pid: int) -> Optional[dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM processes WHERE pid = ?", (pid,))
        row = cur.fetchone()
    return dict(row) if row else None


def list_processes(state: Optional[str] = None) -> list[dict[str, Any]]:
    with db_cursor() as cur:
        if state:
            cur.execute("SELECT * FROM processes WHERE state = ? ORDER BY pid", (state,))
        else:
            cur.execute("SELECT * FROM processes ORDER BY pid")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def update_process(pid: int, **fields: Any) -> Optional[dict[str, Any]]:
    if not fields:
        return get_process(pid)
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [pid]
    with db_cursor() as cur:
        cur.execute(f"UPDATE processes SET {columns} WHERE pid = ?", values)
    return get_process(pid)


def delete_process(pid: int) -> bool:
    with db_cursor() as cur:
        cur.execute("DELETE FROM processes WHERE pid = ?", (pid,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Error / diagnosis / recovery logging
# ---------------------------------------------------------------------------

def log_error(pid: Optional[int], error_type: str, raw_details: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO errors (pid, error_type, detected_at, raw_details) VALUES (?, ?, ?, ?)",
            (pid, error_type, now_iso(), raw_details),
        )
        return cur.lastrowid


def log_diagnosis(error_id: int, diagnosis_text: str) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO diagnoses (error_id, diagnosis_text, created_at) VALUES (?, ?, ?)",
            (error_id, diagnosis_text, now_iso()),
        )
        return cur.lastrowid


def log_recovery_action(error_id: int, action_type: str, target_pid: Optional[int]) -> int:
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO recovery_actions (error_id, action_type, target_pid, executed_at) VALUES (?, ?, ?, ?)",
            (error_id, action_type, target_pid, now_iso()),
        )
        return cur.lastrowid


def get_error_log() -> list[dict[str, Any]]:
    """Join errors + diagnoses + recovery_actions into one historical log."""
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT
                e.error_id, e.pid, e.error_type, e.detected_at, e.raw_details,
                d.diagnosis_id, d.diagnosis_text,
                r.action_id, r.action_type, r.target_pid, r.executed_at
            FROM errors e
            LEFT JOIN diagnoses d ON d.error_id = e.error_id
            LEFT JOIN recovery_actions r ON r.error_id = e.error_id
            ORDER BY e.error_id DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]
    return rows
