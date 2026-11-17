from __future__ import annotations

import json
import uuid
from typing import Any

from app import store


def create(destination: str, service_model: str, plan: dict[str, Any]) -> dict[str, Any]:
    deployment_id = str(uuid.uuid4())
    now = store.iso_now()
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO deployments(
                deployment_id, destination, service_model, plan_json, status,
                approved_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'planned', NULL, ?, ?)""",
            (deployment_id, destination, service_model, json.dumps(plan), now, now),
        )
    return get(deployment_id)  # type: ignore[return-value]


def get(deployment_id: str) -> dict[str, Any] | None:
    with store._connect() as connection:
        row = connection.execute(
            "SELECT * FROM deployments WHERE deployment_id=?", (deployment_id,)
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    result["plan"] = json.loads(result.pop("plan_json"))
    return result


def approve(deployment_id: str, approved_by: str) -> dict[str, Any] | None:
    now = store.iso_now()
    with store._connect() as connection:
        cursor = connection.execute(
            """UPDATE deployments SET status='approved', approved_by=?, updated_at=?
               WHERE deployment_id=? AND status='planned'""",
            (approved_by[:128], now, deployment_id),
        )
        if cursor.rowcount != 1:
            return None
    store.record_event("deployment.approved", deployment_id, {"approved_by": approved_by[:128]})
    return get(deployment_id)


def set_status(deployment_id: str, status: str) -> dict[str, Any] | None:
    allowed = {"executing", "succeeded", "failed"}
    if status not in allowed:
        raise ValueError("Invalid deployment status")
    now = store.iso_now()
    with store._connect() as connection:
        cursor = connection.execute(
            """UPDATE deployments SET status=?, updated_at=?
               WHERE deployment_id=? AND status IN ('approved', 'executing')""",
            (status, now, deployment_id),
        )
        if cursor.rowcount != 1:
            return None
    return get(deployment_id)
