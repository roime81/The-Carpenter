from __future__ import annotations

import re
from typing import Any

from app import store
from app.deployment_store import reconcile_status
from app import infrastructure_twin


def _clean(value: Any, limit: int = 700) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(token|password|secret|api[_-]?key)(\s*[:=]\s*)[^\s,;]+", r"\1\2[redacted]", text)
    return text[:limit]


def _markdown_blueprint(plan: dict[str, Any], prompt: str) -> str:
    requested = plan.get("requested", {})
    resources = (plan.get("iac_bundle") or {}).get("resources", [])
    placement = plan.get("placement") or {}
    lines = [
        "# Infrastructure Workbook",
        "",
        f"> Deployment: {plan.get('deployment_id', 'pending')}",
        "",
        "## 1. Outcome",
        _clean(prompt, 1800) or "Infrastructure outcome captured in the saved deployment request.",
        "",
        "## 2. Target environment",
        f"- Destination: **{requested.get('destination', plan.get('destination', 'n/a'))}**",
        f"- Service model: **{requested.get('service_model', plan.get('service_model', 'n/a')).upper()}**",
        f"- Workload: **{requested.get('name', 'carpenter-app')}**",
        f"- Namespace: **{requested.get('namespace', 'default')}**",
        "",
        "## 3. Capacity and topology",
        f"- Requested instances / replicas: {requested.get('vm_count', 1)}",
        f"- vCPU per instance: {requested.get('vcpu_per_vm', 2)}",
        f"- Memory per instance: {requested.get('memory_gb_per_vm', 4)} GiB",
        f"- Disk per instance: {requested.get('disk_gb_per_vm', 40)} GiB",
        f"- High availability requested: {'Yes' if requested.get('high_availability') else 'No'}",
        f"- Online hosts assessed: {plan.get('host_count', 0)}",
        f"- Capacity readiness: {'Ready' if plan.get('capacity_ready') else 'Needs attention'}",
        f"- HA readiness: {'Ready' if plan.get('ha_ready') else 'Needs attention'}",
        "",
        "## 4. Placement",
    ]
    placements = placement.get("placements", []) if isinstance(placement, dict) else []
    if placements:
        lines.extend(
            f"- {item.get('vm_name', item.get('name', 'Instance'))}: worker {item.get('host_id', item.get('node_id', item.get('worker_id', 'unassigned')))}"
            for item in placements
        )
    else:
        lines.append("- Placement is defined by the selected provider adapter and saved resource graph.")
    lines.extend(["", "## 5. Resource inventory"])
    for item in resources:
        lines.append(
            f"- {item.get('resource_id', 'resource')} — {item.get('provider', 'provider')} / "
            f"{item.get('kind', 'resource')} (worker: {item.get('worker_id', 'provider-managed')})"
        )
    if not resources:
        lines.append("- No provider resources were emitted by the current plan.")
    lines.extend([
        "",
        "## 6. Execution capabilities",
        f"- Provider adapter readiness: {'Ready' if plan.get('adapter_ready') else 'Needs attention'}",
        f"- IaC fingerprint: {(plan.get('iac_bundle') or {}).get('fingerprint', 'n/a')}",
        f"- Static validation: {'Passed' if (plan.get('iac_validation') or {}).get('valid') else 'Not passed'}",
        "",
        "## 7. Guardrails",
        "- This workbook describes the saved plan; no infrastructure is changed by workbook generation.",
        "- Provider mutations require explicit human approval and are dispatched only to eligible enrolled workers.",
        "- The deployment status is reconciled from the actual linked worker jobs.",
    ])
    return "\n".join(lines)


def _playbook_steps(plan: dict[str, Any], deployment: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    deployment = deployment or {}
    status = deployment.get("status", "planned")
    jobs = deployment.get("jobs", [])
    if status == "failed":
        provision_status = "failed"
    elif status == "succeeded":
        provision_status = "succeeded"
    elif status == "executing":
        provision_status = "running" if any(job.get("status") == "running" for job in jobs) else "queued"
    else:
        provision_status = "waiting"
    approval_status = "succeeded" if status in {"approved", "executing", "succeeded"} else ("succeeded" if status == "failed" and plan.get("ready_to_execute_after_approval") else "waiting")
    return [
        {"id": "discover", "title": "Discover enrolled infrastructure", "status": "succeeded" if plan.get("host_count", 0) else "waiting", "detail": f"Assessed {plan.get('host_count', 0)} online host(s) and their advertised capabilities."},
        {"id": "design", "title": "Create infrastructure blueprint", "status": "succeeded", "detail": "Stored the requested outcome, target topology, placement and provider decisions."},
        {"id": "compile", "title": "Generate and validate IaC", "status": "succeeded" if (plan.get("iac_validation") or {}).get("valid") else "failed", "detail": f"Fingerprint: {(plan.get('iac_bundle') or {}).get('fingerprint', 'not available')}"},
        {"id": "approve", "title": "Human approval gate", "status": approval_status, "detail": f"Approval state: {status}. The model cannot approve its own infrastructure changes."},
        {"id": "dispatch", "title": "Dispatch provider functions", "status": provision_status, "detail": f"{len(jobs)} linked provider job(s) currently recorded."},
        {"id": "verify", "title": "Verify and reconcile cloud state", "status": "succeeded" if status == "succeeded" else ("failed" if status == "failed" else "waiting"), "detail": "Completion is based on all linked provider jobs, not on queue acceptance."},
    ]


def attach_canvas_artifacts(plan: dict[str, Any], prompt: str) -> dict[str, Any]:
    """Persist workbook and playbook previews inside the authoritative deployment plan."""
    generated_at = store.iso_now()
    deployment_id = str(plan.get("deployment_id", ""))
    plan["canvas_artifacts"] = {
        "blueprint": {
            "id": f"{deployment_id}:blueprint", "kind": "blueprint",
            "title": "Infrastructure Workbook", "filename": "infrastructure-workbook.md",
            "generated_at": generated_at, "format": "text/markdown",
            "content": _markdown_blueprint(plan, prompt),
        },
        "playbook": {
            "id": f"{deployment_id}:playbook", "kind": "playbook",
            "title": "Execution Playbook", "filename": "execution-playbook.md",
            "generated_at": generated_at, "format": "text/markdown",
            "steps": _playbook_steps(plan),
        },
    }
    return plan


def get_canvas_artifact(session_id: str, kind: str) -> dict[str, Any] | None:
    if kind not in {"blueprint", "playbook"}:
        return None
    state = store.get_state(session_id)
    deployment_id = state.get("deployment_id")
    if not deployment_id:
        return None
    record = reconcile_status(str(deployment_id))
    if not record:
        return None
    artifact = (record.get("plan") or {}).get("canvas_artifacts", {}).get(kind)
    if not artifact:
        return None
    result = dict(artifact)
    if kind == "playbook":
        result["steps"] = _playbook_steps(record.get("plan", {}), record)
        result["content"] = "\n".join(
            [f"# {result.get('title', 'Execution Playbook')}", "", f"> Deployment: {deployment_id}", ""] +
            [f"## {index + 1}. {step['title']} — **{step['status'].upper()}**\n{step['detail']}" for index, step in enumerate(result["steps"])]
        )
    return result


def _event_message(event: dict[str, Any]) -> str:
    detail = event.get("detail", {})
    event_type = event.get("event_type", "")
    worker = detail.get("worker_id")
    function = detail.get("function_name")
    if event_type.endswith("claimed"):
        return f"{function or 'Worker function'} started on {worker or 'worker'}"
    if event_type.endswith("succeeded"):
        return f"{function or 'Worker function'} completed successfully on {worker or 'worker'}"
    if event_type.endswith("failed"):
        return f"{function or 'Worker function'} reported a failure: {_clean(detail.get('error'), 240)}"
    if event_type.endswith("queued"):
        return f"{function or 'Work'} queued for execution"
    if event_type.startswith("deployment.status."):
        return f"Deployment status changed to {event_type.rsplit('.', 1)[-1]}"
    if event_type.startswith("twin.resource."):
        return f"Digital twin {event_type.rsplit('.', 1)[-1]} · {detail.get('resource_type', 'resource')} · {detail.get('name', event.get('subject_id'))} · {detail.get('status', 'observed')}"
    if event_type.startswith("twin.relationship."):
        return f"Topology relationship observed · {detail.get('relation', 'related_to')} · {event.get('subject_id')}"
    return _clean(event_type.replace(".", " "), 180)


def build_canvas_snapshot(session_id: str) -> dict[str, Any]:
    messages = store.list_messages(session_id, limit=100)
    state = store.get_state(session_id)
    deployment_id = state.get("deployment_id")
    deployment = reconcile_status(str(deployment_id)) if deployment_id else None
    plan = (deployment or {}).get("plan", {})
    jobs = [
        job for job in store.list_jobs(500)
        if job.get("payload", {}).get("session_id") == session_id
        or (deployment_id and job.get("payload", {}).get("deployment_id") == deployment_id)
    ]
    job_ids = {job["job_id"] for job in jobs}
    raw_events = store.list_events(500)
    events = [
        event for event in raw_events
        if event.get("detail", {}).get("session_id") == session_id
        or (deployment_id and (
            event.get("subject_id") == deployment_id
            or event.get("detail", {}).get("deployment_id") == deployment_id
        ))
        or event.get("subject_id") in job_ids
        or str(event.get("event_type", "")).startswith("twin.")
    ]
    events.sort(key=lambda item: item.get("created_at", ""))

    by_job: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("subject_id") in job_ids:
            by_job.setdefault(event["subject_id"], []).append(event)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    def add_node(node_id: str, label: str, kind: str, status: str, **details: Any) -> None:
        nodes.append({"id": node_id, "label": _clean(label, 120), "kind": kind, "status": status, **details})

    def link(source: str, target: str, kind: str = "dependency") -> None:
        if source and target and source != target:
            edges.append({"source": source, "target": target, "kind": kind})

    first_message = messages[0] if messages else {}
    has_intent = any(item.get("role") == "user" for item in messages)
    add_node("stage:root", "The Carpenter", "launcher", "ready" if has_intent else "idle",
             description="The authenticated agent launcher and orchestration root.",
             created_at=first_message.get("created_at"))
    if has_intent:
        user_message = next(item for item in messages if item.get("role") == "user")
        add_node("stage:intent", "Intent", "stage", "succeeded",
                 description=_clean(user_message.get("content"), 900),
                 created_at=user_message.get("created_at"), updated_at=user_message.get("created_at"))
        link("stage:root", "stage:intent")

    discovery_jobs = [job for job in jobs if str(job.get("function_name", "")).startswith("discovery.")]
    def aggregate_status(items: list[dict[str, Any]]) -> str:
        statuses = [item.get("status") for item in items]
        if any(value in {"dead", "failed"} for value in statuses):
            return "failed"
        if any(value == "running" for value in statuses):
            return "running"
        if any(value == "queued" for value in statuses):
            return "queued"
        if any(
            item.get("status") == "succeeded"
            and isinstance(item.get("result"), dict)
            and item["result"].get("inventory_complete") is False
            for item in items
        ):
            return "partial"
        if statuses and all(value == "succeeded" for value in statuses):
            return "succeeded"
        if statuses:
            return "queued"
        return "waiting" if has_intent else "idle"

    if has_intent or discovery_jobs:
        add_node("stage:discovery", "Discovery", "stage", aggregate_status(discovery_jobs),
                 description=f"{len(discovery_jobs)} read-only discovery job(s) are associated with this session.",
                 job_count=len(discovery_jobs),
                 updated_at=max((job.get("updated_at", "") for job in discovery_jobs), default=None))
        link("stage:intent", "stage:discovery")

    artifacts = (plan.get("canvas_artifacts") or {}) if deployment else {}
    if deployment:
        add_node("stage:blueprint", "Infrastructure Workbook", "artifact", "succeeded",
                 description="Persisted infrastructure workbook generated from the saved deployment plan.",
                 artifact_kind="blueprint", created_at=artifacts.get("blueprint", {}).get("generated_at"))
        add_node("stage:playbook", "Execution Playbook", "artifact", "succeeded",
                 description="Persisted deployment steps refreshed from actual job and deployment state.",
                 artifact_kind="playbook", created_at=artifacts.get("playbook", {}).get("generated_at"))
        link("stage:intent", "stage:blueprint")
        link("stage:discovery", "stage:blueprint")
        link("stage:blueprint", "stage:playbook")

        validation = plan.get("iac_validation") or {}
        add_node("stage:functions", "Native Functions", "stage",
                 "succeeded" if plan.get("adapter_ready") else "failed",
                 description="Versioned provider functions and worker assignments selected by the plan.",
                 updated_at=deployment.get("updated_at"))
        add_node("stage:iac", "IaC Resource Graph", "stage",
                 "succeeded" if validation.get("valid") else "failed",
                 description=f"Deterministic IaC bundle · fingerprint {(plan.get('iac_bundle') or {}).get('fingerprint', 'n/a')}",
                 updated_at=deployment.get("updated_at"))
        dep_status = deployment.get("status", "planned")
        approval = "succeeded" if dep_status in {"approved", "executing", "succeeded"} or (dep_status == "failed" and plan.get("ready_to_execute_after_approval")) else ("failed" if dep_status == "failed" else "waiting")
        add_node("stage:approval", "Human Approval", "stage", approval,
                 description=f"Deployment approval state: {dep_status}. Approval is explicit and separate from model output.",
                 updated_at=deployment.get("updated_at"))
        provision_status = "succeeded" if dep_status == "succeeded" else ("failed" if dep_status == "failed" else ("running" if dep_status == "executing" else "waiting"))
        add_node("stage:provision", "Provisioning", "stage", provision_status,
                 description="Distributed provider jobs executing on enrolled data-plane workers.",
                 updated_at=deployment.get("updated_at"))
        verify_status = "succeeded" if dep_status == "succeeded" else ("failed" if dep_status == "failed" else "waiting")
        add_node("stage:verified", "Verified Cloud", "stage", verify_status,
                 description="Final state is reconciled only after the linked provider jobs have returned.",
                 updated_at=deployment.get("updated_at"))
        link("stage:blueprint", "stage:functions")
        link("stage:blueprint", "stage:iac")
        link("stage:functions", "stage:iac")
        link("stage:playbook", "stage:approval")
        link("stage:iac", "stage:approval")
        link("stage:approval", "stage:provision")
        link("stage:provision", "stage:verified")

        for resource in (plan.get("iac_bundle") or {}).get("resources", [])[:80]:
            resource_id = str(resource.get("resource_id", "resource"))
            related_jobs = [job for job in jobs if ((job.get("payload") or {}).get("iac_resource") or {}).get("resource_id") == resource_id]
            resource_status = aggregate_status(related_jobs) if related_jobs else ("succeeded" if dep_status == "succeeded" else ("failed" if dep_status == "failed" else "waiting"))
            add_node(f"resource:{resource_id}", str(resource.get("name") or resource_id), "resource", resource_status,
                     description=f"{resource.get('provider', 'Provider')} · {resource.get('kind', 'resource')}",
                     resource_id=resource_id, worker_id=resource.get("worker_id"), parent_id="stage:iac")
            link("stage:iac", f"resource:{resource_id}", "resource")

    worker_nodes: dict[str, dict[str, Any]] = {}
    for job in jobs:
        job_id = job["job_id"]
        history = by_job.get(job_id, [])
        logs = [{"at": event.get("created_at"), "message": _event_message(event), "event_type": event.get("event_type")} for event in history]
        if not logs:
            logs.append({"at": job.get("created_at"), "message": f"Queued {job.get('function_name')}."})
        status_map = {"queued": "queued", "running": "running", "succeeded": "succeeded", "dead": "failed"}
        ui_status = status_map.get(job.get("status"), "waiting")
        result_payload = job.get("result") if isinstance(job.get("result"), dict) else {}
        inventory_partial = job.get("status") == "succeeded" and result_payload.get("inventory_complete") is False
        if inventory_partial:
            ui_status = "partial"
            warning_count = len(result_payload.get("warnings") or [])
            logs.append({
                "at": job.get("updated_at"),
                "message": f"Inventory is partial; {warning_count} provider read warning(s) were recorded.",
                "event_type": "twin.inventory.partial",
            })
        stage_id = "stage:discovery" if str(job.get("function_name", "")).startswith("discovery.") else "stage:provision"
        worker_id = job.get("worker_id") or job.get("target_worker_id") or next((event.get("detail", {}).get("worker_id") for event in reversed(history) if event.get("detail", {}).get("worker_id")), None)
        label = str(job.get("function_name", "Worker job")).split(".")[-1]
        add_node(f"job:{job_id}", label, "job", ui_status,
                 description=f"{job.get('function_name')}@{job.get('function_version')} · attempt {job.get('attempt')}/{job.get('max_attempts')}",
                 job_id=job_id, function_name=job.get("function_name"),
                 function_version=job.get("function_version"), attempt=job.get("attempt"),
                 max_attempts=job.get("max_attempts"), worker_id=worker_id,
                 created_at=job.get("created_at"), updated_at=job.get("updated_at"),
                 started_at=next((event.get("created_at") for event in history if event.get("event_type") == "faas.job.claimed"), None),
                 completed_at=job.get("updated_at") if job.get("status") in {"succeeded", "dead"} else None,
                 error=_clean(job.get("error"), 900), logs=logs, parent_id=stage_id,
                 inventory_complete=result_payload.get("inventory_complete"),
                 inventory_warning_count=len(result_payload.get("warnings") or []))
        if stage_id in {node["id"] for node in nodes}:
            link(stage_id, f"job:{job_id}", "job")
        if worker_id:
            worker_nodes.setdefault(worker_id, {"jobs": [], "statuses": [], "logs": [], "first": job.get("created_at")})
            worker_nodes[worker_id]["jobs"].append(job)
            worker_nodes[worker_id]["statuses"].append(job.get("status"))
            worker_nodes[worker_id]["logs"].extend(logs)
            if job.get("worker_id") or history:
                link(f"job:{job_id}", f"worker:{worker_id}", "worker")
            if stage_id in {node["id"] for node in nodes}:
                link(stage_id, f"worker:{worker_id}", "worker")
        resource = (job.get("payload") or {}).get("iac_resource") or {}
        resource_id = resource.get("resource_id")
        if resource_id and deployment:
            link(f"resource:{resource_id}", f"job:{job_id}", "worker")

    for worker_id, record in worker_nodes.items():
        statuses = record["statuses"]
        worker_status = "failed" if any(value == "dead" for value in statuses) else ("running" if any(value == "running" for value in statuses) else ("succeeded" if statuses and all(value == "succeeded" for value in statuses) else "queued"))
        worker = store.get_agent(worker_id) or {}
        add_node(f"worker:{worker_id}", worker.get("hostname", worker_id), "worker", worker_status,
                 description=f"Enrolled worker {worker_id} · {'online' if worker.get('online') else 'offline or not recently seen'}",
                 worker_id=worker_id, created_at=record.get("first"), updated_at=worker.get("last_seen"),
                 capabilities=list((worker.get("capabilities") or {}).keys())[:16],
                 job_count=len(record["jobs"]),
                 logs=sorted(record["logs"], key=lambda item: item.get("at") or "")[-20:],
                 started_at=next((item.get("at") for item in record["logs"] if item.get("event_type") == "faas.job.claimed"), None),
                 completed_at=max((item.get("at") for item in record["logs"] if item.get("event_type") == "faas.job.succeeded"), default=None))

    # The infrastructure topology is installation-wide shared observed state.
    # Workflow jobs remain scoped to this signed-in conversation.
    digital_twin = infrastructure_twin.list_twin_snapshot(500)
    for resource in digital_twin["resources"]:
        rid = resource["resource_id"]
        add_node(
            rid, resource.get("name") or resource.get("native_id"), "topology",
            resource.get("status", "observed"),
            description=f"{resource.get('resource_type')} · {resource.get('provider')} · {resource.get('native_id')}",
            resource_type=resource.get("resource_type"),
            provider=resource.get("provider"),
            native_id=resource.get("native_id"),
            worker_id=resource.get("worker_id"),
            deployment_id=resource.get("deployment_id"),
            properties=resource.get("properties", {}),
            version=resource.get("version", 1),
            source=resource.get("source"),
            created_at=resource.get("first_seen"),
            updated_at=resource.get("last_seen"),
            logs=[],
            resource_id=rid,
        )
    for relation in digital_twin["relationships"]:
        edges.append({
            "source": relation["source_resource_id"],
            "target": relation["target_resource_id"],
            "kind": relation["relation"],
        })
    control_id = infrastructure_twin.CONTROL_PLANE_ID
    if control_id in {item["id"] for item in nodes}:
        link("stage:root", control_id, "control_plane")
    for worker_id in worker_nodes:
        host_id = infrastructure_twin.resource_id("carpenter-agent", worker_id)
        if host_id in {item["id"] for item in nodes}:
            link(f"worker:{worker_id}", host_id, "worker_host")

    safe_events = [{
        "event_id": event.get("event_id"), "event_type": event.get("event_type"),
        "subject_id": event.get("subject_id"), "created_at": event.get("created_at"),
        "message": _event_message(event),
    } for event in events[-80:]]
    return {
        "deployment_id": deployment_id,
        "deployment_status": (deployment or {}).get("status"),
        "nodes": nodes, "edges": edges, "events": safe_events,
        "digital_twin": {
            "resource_count": digital_twin["resource_count"],
            "relationship_count": digital_twin["relationship_count"],
            "updated_at": digital_twin["updated_at"],
            "counts_by_type": {kind: sum(1 for item in digital_twin["resources"] if item["resource_type"] == kind) for kind in sorted({item["resource_type"] for item in digital_twin["resources"]})},
        },
        "artifacts": [
            {"kind": kind, "title": item.get("title"), "filename": item.get("filename"),
             "generated_at": item.get("generated_at")}
            for kind, item in artifacts.items()
        ],
        "updated_at": max(
            [item.get("updated_at") or item.get("created_at") or "" for item in nodes]
            + [event.get("created_at", "") for event in safe_events], default=""
        ),
    }
