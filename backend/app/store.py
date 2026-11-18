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
        connection.execute("PRAGMA journal_mode = WAL")
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
                target_worker_id TEXT,
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
            CREATE TABLE IF NOT EXISTS deployment_job_links (
                deployment_id TEXT NOT NULL,
                job_id TEXT NOT NULL UNIQUE,
                component TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(deployment_id, job_id),
                FOREIGN KEY(deployment_id) REFERENCES deployments(deployment_id),
                FOREIGN KEY(job_id) REFERENCES faas_jobs(job_id)
            );
            CREATE INDEX IF NOT EXISTS idx_deployment_job_links_deployment
                ON deployment_job_links(deployment_id);
            CREATE TABLE IF NOT EXISTS operation_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                subject_id TEXT,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS twin_resources (
                resource_id TEXT PRIMARY KEY,
                resource_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                native_id TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                source TEXT NOT NULL,
                worker_id TEXT,
                deployment_id TEXT,
                properties_json TEXT NOT NULL DEFAULT '{}',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                UNIQUE(provider, native_id)
            );
            CREATE INDEX IF NOT EXISTS idx_twin_resources_type
                ON twin_resources(resource_type, provider, status);
            CREATE INDEX IF NOT EXISTS idx_twin_resources_worker
                ON twin_resources(worker_id);
            CREATE TABLE IF NOT EXISTS twin_relationships (
                source_resource_id TEXT NOT NULL,
                target_resource_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                source TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY(source_resource_id, target_resource_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_twin_relationships_target
                ON twin_relationships(target_resource_id, relation);
            CREATE TABLE IF NOT EXISTS twin_observations (
                observation_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                previous_status TEXT,
                status TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_twin_observations_resource
                ON twin_observations(resource_id, observed_at);
            """
        )
        # Forward-compatible migration for databases created by earlier 0.2.0
        # pre-release commits before worker-specific routing existed.
        job_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(faas_jobs)").fetchall()
        }
        if "target_worker_id" not in job_columns:
            connection.execute("ALTER TABLE faas_jobs ADD COLUMN target_worker_id TEXT")


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
        existing = connection.execute(
            "SELECT inventory_json FROM agents WHERE node_id = ?",
            (inventory["node_id"],),
        ).fetchone()
        if existing:
            previous = json.loads(existing["inventory_json"])
            # Keep detailed discovery results from worker jobs; a regular
            # heartbeat must not erase information collected between heartbeats.
            previous_discovery = previous.get("discovery", {})
            current_discovery = inventory.get("discovery", {})
            merged_discovery = {**previous_discovery, **current_discovery}
            for key, value in current_discovery.items():
                if isinstance(value, dict) and isinstance(previous_discovery.get(key), dict):
                    merged_discovery[key] = {**previous_discovery[key], **value}
            inventory["discovery"] = merged_discovery
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


def merge_agent_discovery(node_id: str, function_name: str, result: dict[str, Any]) -> None:
    """Persist detailed node inspection results without changing heartbeat freshness."""
    with _connect() as connection:
        row = connection.execute(
            "SELECT inventory_json FROM agents WHERE node_id = ?", (node_id,)
        ).fetchone()
        if not row:
            return
        inventory = json.loads(row["inventory_json"])
        discovery = inventory.setdefault("discovery", {})
        if function_name == "discovery.hypervisor_probe":
            discovery["hypervisor"] = result
        elif function_name == "discovery.storage_network":
            discovery["storage_network"] = result
        elif function_name == "discovery.host_inventory":
            for key in (
                "hostname", "operating_system", "architecture", "cpu_cores",
                "memory_total_bytes", "memory_available_bytes",
                "disk_total_bytes", "disk_free_bytes",
            ):
                if key in result:
                    inventory[key] = result[key]
        connection.execute(
            "UPDATE agents SET inventory_json = ? WHERE node_id = ?",
            (json.dumps(inventory), node_id),
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
    target_worker_id: str | None = None,
) -> dict[str, Any]:
    now = iso_now()
    job_id = str(uuid.uuid4())
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
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
                target_worker_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id, function_name, function_version, json.dumps(payload), priority,
                max(1, min(max_attempts, 20)), now, idempotency_key, target_worker_id, now, now,
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

        worker = connection.execute(
            "SELECT inventory_json, last_seen FROM agents WHERE node_id = ?",
            (worker_id,),
        ).fetchone()
        if not worker:
            return None
        if (now - datetime.fromisoformat(worker["last_seen"])).total_seconds() > settings.agent_stale_seconds:
            return None
        capabilities = json.loads(worker["inventory_json"]).get("capabilities", {})

        candidates = connection.execute(
            """SELECT * FROM faas_jobs
               WHERE status='queued' AND available_at <= ?
               ORDER BY priority ASC, created_at ASC LIMIT 100""",
            (now_text,),
        ).fetchall()

        eligible = next(
            (
                candidate for candidate in candidates
                if capabilities.get(candidate["function_name"]) == candidate["function_version"]
                and candidate["target_worker_id"] in (None, worker_id)
            ),
            None,
        )
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
               WHERE job_id=? AND status='running' AND worker_id=? AND lease_token=?
                 AND lease_until > ?""",
            (json.dumps(result), now, job_id, worker_id, lease_token, now),
        )
        return cursor.rowcount == 1


def fail_job(job_id: str, worker_id: str, lease_token: str, error: str) -> bool:
    now_dt = utcnow()
    now = now_dt.isoformat()
    with _connect() as connection:
        row = connection.execute(
            """SELECT attempt, max_attempts FROM faas_jobs
               WHERE job_id=? AND status='running' AND worker_id=? AND lease_token=?
                 AND lease_until > ?""",
            (job_id, worker_id, lease_token, now),
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



def link_deployment_job(deployment_id: str, job_id: str, component: str) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT OR IGNORE INTO deployment_job_links(
                deployment_id, job_id, component, created_at
            ) VALUES (?, ?, ?, ?)""",
            (deployment_id, job_id, component[:160], iso_now()),
        )


def list_deployment_job_links(deployment_id: str) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT deployment_id, job_id, component, created_at
               FROM deployment_job_links WHERE deployment_id = ?
               ORDER BY created_at, component""",
            (deployment_id,),
        ).fetchall()
    return [dict(row) for row in rows]


# Infrastructure Digital Twin — observed resource inventory

def upsert_twin_resource(resource: dict[str, Any]) -> dict[str, Any]:
    required = ("resource_id", "resource_type", "provider", "native_id", "name", "status", "source")
    if any(not str(resource.get(key, "")).strip() for key in required):
        raise ValueError("A digital-twin resource requires stable identity, type, provider, name, status and source.")
    now = iso_now()
    properties = resource.get("properties") or {}
    if not isinstance(properties, dict):
        raise ValueError("Digital-twin resource properties must be a JSON object.")
    properties_json = json.dumps(properties, sort_keys=True, separators=(",", ":"), default=str)
    change = None
    previous_status = None
    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM twin_resources WHERE resource_id=? OR (provider=? AND native_id=?)",
            (resource["resource_id"], resource["provider"], resource["native_id"]),
        ).fetchone()
        if existing:
            previous_status = existing["status"]
            changed = (
                existing["resource_type"] != resource["resource_type"]
                or existing["name"] != resource["name"]
                or existing["status"] != resource["status"]
                or existing["properties_json"] != properties_json
                or existing["worker_id"] != resource.get("worker_id")
                or existing["deployment_id"] != resource.get("deployment_id")
            )
            version = int(existing["version"]) + (1 if changed else 0)
            connection.execute(
                """UPDATE twin_resources SET resource_type=?, provider=?, native_id=?, name=?,
                   status=?, source=?, worker_id=?, deployment_id=?, properties_json=?,
                   last_seen=?, updated_at=?, version=? WHERE resource_id=?""",
                (
                    resource["resource_type"], resource["provider"], resource["native_id"],
                    resource["name"][:200], resource["status"], resource["source"],
                    resource.get("worker_id"), resource.get("deployment_id"), properties_json,
                    now, now, version, existing["resource_id"],
                ),
            )
            resource_id = existing["resource_id"]
            change = "changed" if changed else None
        else:
            resource_id = resource["resource_id"]
            version = 1
            connection.execute(
                """INSERT INTO twin_resources(
                    resource_id, resource_type, provider, native_id, name, status, source,
                    worker_id, deployment_id, properties_json, first_seen, last_seen,
                    updated_at, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    resource_id, resource["resource_type"], resource["provider"], resource["native_id"],
                    resource["name"][:200], resource["status"], resource["source"],
                    resource.get("worker_id"), resource.get("deployment_id"), properties_json,
                    now, now, now, 1,
                ),
            )
            change = "created"
        if change:
            snapshot = {
                "resource_id": resource_id, "resource_type": resource["resource_type"],
                "provider": resource["provider"], "native_id": resource["native_id"],
                "name": resource["name"][:200], "status": resource["status"],
                "source": resource["source"], "worker_id": resource.get("worker_id"),
                "deployment_id": resource.get("deployment_id"), "properties": properties,
                "version": version,
            }
            connection.execute(
                """INSERT INTO twin_observations(
                    observation_id, resource_id, change_type, previous_status, status,
                    snapshot_json, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), resource_id, change, previous_status,
                 resource["status"], json.dumps(snapshot, sort_keys=True, default=str), now),
            )
    if change:
        record_event("twin.resource." + change, resource_id, {
            "resource_type": resource["resource_type"], "provider": resource["provider"],
            "name": resource["name"][:200], "status": resource["status"],
            "version": version, "source": resource["source"],
        })
    return get_twin_resource(resource_id)  # type: ignore[return-value]


def get_twin_resource(resource_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM twin_resources WHERE resource_id=?", (resource_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["properties"] = json.loads(item.pop("properties_json"))
    return item


def list_twin_resources(limit: int = 500) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM twin_resources ORDER BY resource_type, provider, name LIMIT ?",
            (max(1, min(limit, 2000)),),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["properties"] = json.loads(item.pop("properties_json"))
        result.append(item)
    return result


def upsert_twin_relationship(
    source_resource_id: str, target_resource_id: str, relation: str,
    source: str = "discovery", metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not source_resource_id or not target_resource_id or source_resource_id == target_resource_id:
        raise ValueError("Digital-twin relationships require two distinct resource IDs.")
    if not relation or len(relation) > 80:
        raise ValueError("A digital-twin relationship type is required.")
    now = iso_now()
    metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"), default=str)
    with _connect() as connection:
        existing = connection.execute(
            """SELECT * FROM twin_relationships
               WHERE source_resource_id=? AND target_resource_id=? AND relation=?""",
            (source_resource_id, target_resource_id, relation),
        ).fetchone()
        if existing:
            connection.execute(
                """UPDATE twin_relationships SET source=?, metadata_json=?, last_seen=?
                   WHERE source_resource_id=? AND target_resource_id=? AND relation=?""",
                (source, metadata_json, now, source_resource_id, target_resource_id, relation),
            )
            created = False
        else:
            connection.execute(
                """INSERT INTO twin_relationships(
                    source_resource_id, target_resource_id, relation, source,
                    metadata_json, first_seen, last_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_resource_id, target_resource_id, relation, source,
                 metadata_json, now, now),
            )
            created = True
    if created:
        record_event("twin.relationship.created", source_resource_id, {
            "target_resource_id": target_resource_id, "relation": relation, "source": source,
        })
    return {
        "source_resource_id": source_resource_id,
        "target_resource_id": target_resource_id,
        "relation": relation, "source": source,
        "metadata": metadata or {}, "first_seen": now, "last_seen": now,
    }


def list_twin_relationships(limit: int = 2000) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT * FROM twin_relationships
               ORDER BY relation, source_resource_id, target_resource_id LIMIT ?""",
            (max(1, min(limit, 10000)),),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        result.append(item)
    return result


def list_twin_observations(resource_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """SELECT observation_id, resource_id, change_type, previous_status,
               status, snapshot_json, observed_at FROM twin_observations
               WHERE resource_id=? ORDER BY observed_at DESC LIMIT ?""",
            (resource_id, max(1, min(limit, 500))),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["snapshot"] = json.loads(item.pop("snapshot_json"))
        result.append(item)
    return list(reversed(result))
