"""SQLite request log. Schema: CONTRACT.md section 11.

Person 2 owns storage behavior. This file lives in bridge/ because the
team plan puts the log next to the state machine. Agree changes here
before editing. See the ownership note in CONTRACT.md.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bridge.phrases import load_phrases

DB_PATH = Path(__file__).with_name("taptotalk.db")
SOURCES = frozenset({"tap", "keyboard", "ui", "fixed"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS selections (
    id INTEGER PRIMARY KEY,
    phrase_id TEXT NOT NULL,
    category TEXT NOT NULL,
    source TEXT NOT NULL,
    selected_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    escalated INTEGER NOT NULL DEFAULT 0,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
"""


def utc_now() -> str:
    """Current time as ISO 8601 UTC, matching the contract example."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the log database and create the contract tables if needed."""
    path = db_path or DB_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def save_selection(
    phrase_id: str,
    category: str,
    source: str,
    *,
    db_path: Path | None = None,
    selected_at: str | None = None,
) -> int:
    """Insert one selections row and return its id.

    Alert rows use the alerts table and are not written here.
    """
    catalog = load_phrases()
    known = {item["id"]: item["category"] for item in catalog["phrases"]}
    if phrase_id not in known:
        raise ValueError(f"unknown phrase_id: {phrase_id}")
    if known[phrase_id] != category:
        raise ValueError(f"category does not match phrase_id: {phrase_id}")
    if source not in SOURCES:
        raise ValueError("source must be tap, keyboard, ui, or fixed")

    when = utc_now() if selected_at is None else selected_at
    connection = connect(db_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO selections (phrase_id, category, source, selected_at)
            VALUES (?, ?, ?, ?)
            """,
            (phrase_id, category, source, when),
        )
        connection.commit()
        row_id = cursor.lastrowid
    finally:
        connection.close()
    if row_id is None:
        raise RuntimeError("insert did not return a row id")
    return int(row_id)


def recent_phrase_ids(limit: int = 5, *, db_path: Path | None = None) -> list[str]:
    """Return up to ``limit`` phrase ids, oldest first.

    The rows are the newest selections. Only catalog ids are included.
    Timestamps, categories, and sources stay on the laptop.
    """
    if limit < 1:
        return []
    known = {item["id"] for item in load_phrases()["phrases"]}
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT phrase_id FROM selections
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(limit * 4, limit),),
        ).fetchall()
    finally:
        connection.close()
    chosen: list[str] = []
    for row in rows:
        phrase_id = str(row["phrase_id"])
        if phrase_id in known:
            chosen.append(phrase_id)
        if len(chosen) == limit:
            break
    chosen.reverse()
    return chosen
