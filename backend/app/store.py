from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utcnow().isoformat()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 15000")
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
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
            CREATE TABLE IF NOT EXISTS agents (
                node_id TEXT PRIMARY KEY,
                hostname TEXT NOT NULL,
                inventory_json TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS faas_functions (
                function_name TEXT NOT NULL,
                version TEXT NOT NULL,
                description TEXT NOT NULL,
                digest TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                registered_at TEXT NOT NULL,
                PRIMARY KEY(function_name, version)
            );
            CREATE TABLE IF NOT EXISTS faas_jobs (
                job_id TEXT PRIMARY KEY,
                function_name TEXT NOT NULL,
                function_version TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL DEFAULT 100,
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                available_at TEXT NOT NULL,
                lease_until TEXT,
                lease_token TEXT,
                worker_id TEXT,
                result_json TEXT,
                error TEXT,
                idempotency_key TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_faas_idempotency
                ON faas_jobs(function_name, idempotency_key)
                WHERE idempotency_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_faas_queue
                ON faas_jobs(status, priority, available_at, created_at);
            CREATE INDEX IF NOT EXISTS idx_faas_worker
                ON faas_jobs(worker_id, status);
            CREATE TABLE IF NOT EXISTS deployments (
                deployment_id TEXT PRIMARY KEY,
                destination TEXT NOT NULL,
                service_model TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                status TEXT NOT NULL,
                approved_by TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operation_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                subject_id TEXT,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


# Conversation persistence

def ensure_session(session_id: str) -> None:
    now = iso_now()
    with _connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO sessions(session_id, state_json, created_at, updated_at)
               VALUES (?, '{}', ?, ?)""",
            (session_id, now, now),
        )


def add_message(session_id: str, role: str, content: str) -> None:
    ensure_session(session_id)
    now = iso_now()
    with _connect() as connection:
        connection.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        connection.execute(
            "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
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
    now = iso_now()
    with _connect() as connection:
        connection.execute(
            "UPDATE sessions SET state_json = ?, updated_at = ? WHERE session_id = ?",
            (json.dumps(state), now, session_id),
        )


# Node inventory / worker presence

def upsert_agent(inventory: dict[str, Any]) -> None:
    now = iso_now()
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
            (inventory["node_id"], inventory["hostname"], json.dumps(inventory), now, now),
        )


def list_agents(online_only: bool = True) -> list[dict[str, Any]]:
    now = utcnow()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT inventory_json, first_seen, last_seen FROM agents ORDER BY hostname"
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = json.loads(row["inventory_json"])
        last_seen = datetime.fromisoformat(row["last_seen"])
        online = (now - last_seen).total_seconds() <= settings.agent_stale_seconds
        item["first_seen"] = row["first_seen"]
        item["last_seen"] = row["last_seen"]
        item["online"] = online
        if online_only and not online:
            continue
        result.append(item)
    return result


def get_agent(node_id: str) -> dict[str, Any] | None:
    for agent in list_agents(online_only=False):
        if agent["node_id"] == node_id:
            return agent
    return None


# Function catalogue and durable queue

def register_function(
    function_name: str, version: str, description: str, digest: str = "builtin"
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO faas_functions(function_name, version, description, digest, enabled, registered_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(function_name, version) DO UPDATE SET
                description = excluded.description, digest = excluded.digest, enabled = 1
            """,
            (function_name, version, description, digest, iso_now()),
        )


def list_functions() -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT function_name, version, description, digest, enabled, registered_at
               FROM faas_functions ORDER BY function_name, version"""
        ).fetchall()
    return [dict(row) for row in rows]


def enqueue_job(
    function_name: str,
    function_version: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
    priority: int = 100,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    now = iso_now()
    job_id = str(uuid.uuid4())
    with _connect() as connection:
        function = connection.execute(
            """SELECT enabled FROM faas_functions
               WHERE function_name = ? AND version = ?""",
            (function_name, function_version),
        ).fetchone()
        if not function or not function["enabled"]:
            raise ValueError("Function version is not registered or enabled")
        if idempotency_key:
            existing = connection.execute(
                """SELECT * FROM faas_jobs
                   WHERE function_name = ? AND idempotency_key = ?""",
                (function_name, idempotency_key),
            ).fetchone()
            if existing:
                return _job_dict(existing)
        connection.execute(
            """
            INSERT INTO faas_jobs(
                job_id, function_name, function_version, payload_json, status,
                priority, attempt, max_attempts, available_at, idempotency_key,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?, ?, ?)
            """,
            (
                job_id, function_name, function_version, json.dumps(payload), priority,
                max(1, min(max_attempts, 20)), now, idempotency_key, now, now,
            ),
        )
        row = connection.execute("SELECT * FROM faas_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_dict(row)


def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    item["result"] = json.loads(item.pop("result_json")) if item["result_json"] else None
    item.pop("result_json", None)
    item.pop("lease_token", None)
    return item


def claim_job(worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
    now = utcnow()
    now_text = now.isoformat()
    lease_until = (now + timedelta(seconds=max(15, min(lease_seconds, 600)))).isoformat()
    lease_token = str(uuid.uuid4())

    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Recover expired leases before selecting new work.
        expired = connection.execute(
            """SELECT job_id, attempt, max_attempts FROM faas_jobs
               WHERE status = 'running' AND lease_until <= ?""",
            (now_text,),
        ).fetchall()
        for row in expired:
            if row["attempt"] < row["max_attempts"]:
                connection.execute(
                    """UPDATE faas_jobs SET status='queued', worker_id=NULL, lease_token=NULL,
                       lease_until=NULL, available_at=?, updated_at=? WHERE job_id=?""",
                    (now_text, now_text, row["job_id"]),
                )
            else:
                connection.execute(
                    """UPDATE faas_jobs SET status='dead', worker_id=NULL, lease_token=NULL,
                       lease_until=NULL, error='Worker lease expired after maximum attempts',
                       updated_at=? WHERE job_id=?""",
                    (now_text, row["job_id"]),
                )

        candidates = connection.execute(
            """SELECT * FROM faas_jobs
               WHERE status='queued' AND available_at <= ?
               ORDER BY priority ASC, created_at ASC LIMIT 100""",
            (now_text,),
        ).fetchall()

        eligible = None
        for candidate in candidates:
            workers = connection.execute(
                "SELECT node_id, inventory_json, last_seen FROM agents"
            ).fetchall()
            for worker in workers:
                if (now - datetime.fromisoformat(worker["last_seen"])).total_seconds() > settings.agent_stale_seconds:
                    continue
                inventory = json.loads(worker["inventory_json"])
                capabilities = inventory.get("capabilities", {})
                advertised = capabilities.get(candidate["function_name"])
                if advertised == candidate["function_version"]:
                    eligible = candidate
                    if worker["node_id"] == worker_id:
                        break
            if eligible:
                # Route work to the worker asking to claim it, but only if it supports the function.
                worker_row = connection.execute(
                    "SELECT inventory_json, last_seen FROM agents WHERE node_id = ?",
                    (worker_id,),
                ).fetchone()
                if not worker_row:
                    eligible = None
                    continue
                worker_inventory = json.loads(worker_row["inventory_json"])
                if worker_inventory.get("capabilities", {}).get(candidate["function_name"]) != candidate["function_version"]:
                    eligible = None
                    continue
                if (now - datetime.fromisoformat(worker_row["last_seen"])).total_seconds() > settings.agent_stale_seconds:
                    eligible = None
                    continue
                break

        if eligible is None:
            return None

        connection.execute(
            """UPDATE faas_jobs SET status='running', attempt=attempt+1, worker_id=?,
               lease_token=?, lease_until=?, updated_at=? WHERE job_id=? AND status='queued'""",
            (worker_id, lease_token, lease_until, now_text, eligible["job_id"]),
        )
        row = connection.execute(
            "SELECT * FROM faas_jobs WHERE job_id = ?", (eligible["job_id"],)
        ).fetchone()
        result = _job_dict(row)
        result["lease_token"] = lease_token
        return result


def complete_job(job_id: str, worker_id: str, lease_token: str, result: dict[str, Any]) -> bool:
    now = iso_now()
    with _connect() as connection:
        cursor = connection.execute(
            """UPDATE faas_jobs SET status='succeeded', result_json=?, error=NULL,
               lease_until=NULL, lease_token=NULL, updated_at=?
               WHERE job_id=? AND status='running' AND worker_id=? AND lease_token=?""",
            (json.dumps(result), now, job_id, worker_id, lease_token),
        )
        return cursor.rowcount == 1


def fail_job(job_id: str, worker_id: str, lease_token: str, error: str) -> bool:
    now_dt = utcnow()
    now = now_dt.isoformat()
    with _connect() as connection:
        row = connection.execute(
            """SELECT attempt, max_attempts FROM faas_jobs
               WHERE job_id=? AND status='running' AND worker_id=? AND lease_token=?""",
            (job_id, worker_id, lease_token),
        ).fetchone()
        if not row:
            return False
        if row["attempt"] < row["max_attempts"]:
            delay = min(300, 2 ** row["attempt"])
            available = (now_dt + timedelta(seconds=delay)).isoformat()
            status = "queued"
        else:
            available = now
            status = "dead"
        connection.execute(
            """UPDATE faas_jobs SET status=?, error=?, worker_id=NULL, lease_token=NULL,
               lease_until=NULL, available_at=?, updated_at=? WHERE job_id=?""",
            (status, error[:4000], available, now, job_id),
        )
        return True


def get_job(job_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute("SELECT * FROM faas_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_dict(row) if row else None


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM faas_jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
    return [_job_dict(row) for row in rows]


def record_event(event_type: str, subject_id: str | None, detail: dict[str, Any]) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO operation_events(event_id, event_type, subject_id, detail_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), event_type, subject_id, json.dumps(detail), iso_now()),
        )


def list_events(limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM operation_events ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [
        {"event_id": row["event_id"], "event_type": row["event_type"],
         "subject_id": row["subject_id"], "detail": json.loads(row["detail_json"]),
         "created_at": row["created_at"]}
        for row in rows
    ]
