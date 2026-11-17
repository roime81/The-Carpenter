from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialise_store() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                state_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id, id);

            CREATE TABLE IF NOT EXISTS agents (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                inventory_json TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            """
        )


def ensure_session(session_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO sessions(session_id, state_json, created_at, updated_at)
               VALUES (?, '{}', ?, ?)""",
            (session_id, now, now),
        )


def add_message(session_id: str, role: str, content: str) -> None:
    ensure_session(session_id)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )


def list_messages(session_id: str, limit: int = 100) -> list[dict[str, str]]:
    ensure_session(session_id)
    with _connect() as connection:
        rows = connection.execute(
            """SELECT role, content, created_at FROM messages
               WHERE session_id = ? ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_state(session_id: str) -> dict[str, Any]:
    ensure_session(session_id)
    with _connect() as connection:
        row = connection.execute(
            "SELECT state_json FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return json.loads(row["state_json"]) if row else {}


def set_state(session_id: str, state: dict[str, Any]) -> None:
    ensure_session(session_id)
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        connection.execute(
            "UPDATE sessions SET state_json = ?, updated_at = ? WHERE session_id = ?",
            (json.dumps(state), now, session_id),
        )


def upsert_agent(inventory: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    node_id = inventory["node_id"]
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO agents(node_id, hostname, inventory_json, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                hostname = excluded.hostname,
                inventory_json = excluded.inventory_json,
                last_seen = excluded.last_seen
            """,
            (node_id, inventory["hostname"], json.dumps(inventory), now, now),
        )


def list_agents() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT inventory_json, first_seen, last_seen FROM agents ORDER BY hostname"
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = json.loads(row["inventory_json"])
        item["first_seen"] = row["first_seen"]
        item["last_seen"] = row["last_seen"]
        result.append(item)
    return result
