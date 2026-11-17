from __future__ import annotations

import re
import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import store
from app.config import settings
from app.models import (
    AgentHeartbeat, JobEnqueueRequest, JobFailureRequest, JobResultRequest,
    DeploymentPlanInput,
)
from app.orchestrator import CarpenterOrchestrator
from app.resource_engine import plan_placement, forecast_capacity
from app.worker_catalogue import register_worker_functions
from app.deployment_models import DeploymentRequest, DeploymentApproval
from app.deployment_store import (
    create as create_deployment_record,
    get as get_deployment_record,
    approve as approve_deployment_record,
    set_status as set_deployment_status,
    link_job as link_deployment_job,
    reconcile_status as reconcile_deployment_status,
)
from app.deployment_engine import DeploymentEngine
from app.iac_engine import validate_iac_bundle
from app.web_auth import COOKIE_NAME, SESSION_TTL_SECONDS, issue_session, read_session, verify_csrf
from app.operations_engine import assess_high_availability, recommend_action, build_failover_plan, load_balancer_plan

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title="The Carpenter",
    description="An AI Cloud Deployment Agent and AI IaC Agent that discovers, compiles, validates and provisions infrastructure through distributed Python workers.",
    version="0.4.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
orchestrator = CarpenterOrchestrator()


@app.on_event("startup")
def startup() -> None:
    store.initialise_store()
    register_worker_functions()


def _require_agent(token: str) -> None:
    expected = settings.agent_enrollment_token
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credential.")


def _require_admin(token: str) -> None:
    expected = settings.admin_token
    if not expected or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid control-plane credential.")



def _web_identity(request: Request) -> dict[str, Any] | None:
    return read_session(request.cookies.get(COOKIE_NAME))


def _conversation_id(identity: dict[str, Any]) -> str:
    # The conversation ID is a signed session claim; never trust a caller-
    # controlled, unsigned cookie to select another conversation.
    return str(identity["conversation_id"])


def _approve_saved_plan(deployment_id: str, approved_by: str, source: str) -> dict[str, Any]:
    record = get_deployment_record(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment plan not found.")
    if record["status"] != "planned":
        raise HTTPException(status_code=409, detail=f"Deployment is {record['status']}; only a planned deployment can be approved.")
    plan = record.get("plan", {})
    if not plan.get("ready_to_execute_after_approval"):
        raise HTTPException(status_code=409, detail="Plan is not ready: resolve capacity, provider, or HA blockers before approval.")
    bundle = plan.get("iac_bundle")
    if not isinstance(bundle, dict):
        raise HTTPException(status_code=409, detail="The saved plan has no generated IaC bundle.")
    try:
        validate_iac_bundle(bundle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Stored IaC validation failed: {exc}") from exc
    approved = approve_deployment_record(deployment_id, approved_by)
    if not approved:
        raise HTTPException(status_code=409, detail="Deployment approval was already consumed or the plan changed.")
    store.record_event("deployment.approval.source", deployment_id, {
        "source": source,
        "approved_by": approved_by,
        "iac_fingerprint": bundle.get("fingerprint"),
    })
    return approved


def _execute_approved_plan(deployment_id: str, actor: str, source: str) -> dict[str, Any]:
    record = get_deployment_record(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment not found.")
    if record["status"] != "approved":
        raise HTTPException(status_code=409, detail="Deployment must be approved before execution.")
    plan = record.get("plan", {})
    if not plan.get("ready_to_execute_after_approval"):
        raise HTTPException(status_code=409, detail="Deployment plan failed capacity, HA, or provider readiness checks.")
    bundle = plan.get("iac_bundle")
    if not isinstance(bundle, dict):
        raise HTTPException(status_code=409, detail="Generated IaC bundle is missing.")
    try:
        validate_iac_bundle(bundle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Stored IaC validation failed before dispatch: {exc}") from exc

    # Re-assess immediately before mutation. Approval cannot override lost capacity,
    # changed placement, missing provider capability, or a changed worker assignment.
    current_plan = DeploymentEngine().build_plan(
        plan["requested"], store.list_agents(online_only=True)
    )
    if not current_plan.get("ready_to_execute_after_approval"):
        raise HTTPException(status_code=409, detail="Infrastructure readiness changed after approval; create and approve a new plan.")
    if current_plan.get("placement") != plan.get("placement"):
        raise HTTPException(status_code=409, detail="Placement changed after approval; create and approve a fresh plan.")
    if current_plan.get("execution_workers") != plan.get("execution_workers"):
        raise HTTPException(status_code=409, detail="Execution worker capabilities changed after approval; create and approve a fresh plan.")

    # The atomic status transition prevents two browser/API requests dispatching
    # the same approved deployment concurrently.
    transitioned = set_deployment_status(deployment_id, "executing")
    if not transitioned or transitioned.get("status") != "executing":
        raise HTTPException(status_code=409, detail="Deployment execution has already started.")
    store.record_event("deployment.execution.started", deployment_id, {
        "destination": record["destination"],
        "execution_mode": "distributed-python-faas",
        "actor": actor,
        "source": source,
        "iac_fingerprint": bundle.get("fingerprint"),
    })
    try:
        result = DeploymentEngine().execute(deployment_id, plan)
        queued_jobs = result.get("queued_jobs", [])
        if not queued_jobs:
            raise RuntimeError("The deployment compiler produced no executable provider jobs.")
        for job in queued_jobs:
            link_deployment_job(deployment_id, job["job_id"], job["component"])
        store.record_event("deployment.execution.queued", deployment_id, {
            "job_ids": [job["job_id"] for job in queued_jobs],
            "components": [job["component"] for job in queued_jobs],
        })
        return {
            "deployment_id": deployment_id,
            "status": "queued",
            "execution_mode": "distributed-python-faas",
            "jobs": queued_jobs,
            "iac_fingerprint": bundle.get("fingerprint"),
            "message": "Provider functions have been queued on the selected data-plane workers.",
        }
    except Exception as exc:
        set_deployment_status(deployment_id, "failed")
        store.record_event("deployment.execution.failed", deployment_id, {
            "actor": actor,
            "source": source,
            "error": f"{type(exc).__name__}: {exc}",
        })
        raise HTTPException(status_code=502, detail=f"FaaS dispatch failed: {type(exc).__name__}: {exc}") from exc


def _handle_chat_deployment_command(
    session_id: str, identity: dict[str, Any], content: str
) -> str | None:
    command = re.sub(r"[\s.!?]+", " ", content.casefold()).strip()
    commands = {
        "approve": "approve",
        "approve plan": "approve",
        "approve this plan": "approve",
        "approve and deploy": "approve_deploy",
        "approve and execute": "approve_deploy",
        "deploy": "deploy",
        "deploy now": "deploy",
        "execute": "deploy",
        "execute now": "deploy",
        "status": "status",
        "deployment status": "status",
        "check status": "status",
    }
    action = commands.get(command)
    if action is None:
        return None

    state = store.get_state(session_id)
    deployment_id = state.get("deployment_id")
    if not deployment_id:
        return "There is no deployment plan attached to this conversation yet. Describe the infrastructure outcome first."
    actor = str(identity.get("subject", "web-user"))
    role = str(identity.get("role", "viewer"))

    if action == "status":
        record = reconcile_deployment_status(deployment_id)
        if not record:
            return f"I could not find deployment {deployment_id}."
        jobs = record.get("jobs", [])
        lines = [
            f"**Deployment status: {record['status']}**",
            f"- Deployment: {deployment_id}",
            f"- Destination: {record['destination']} / {record['service_model'].upper()}",
            f"- Approved by: {record.get('approved_by') or 'not yet approved'}",
        ]
        if jobs:
            lines.append(f"- Provider jobs: {len(jobs)}")
            lines.extend(
                f"  - {job['component']} — {job['status']} (worker: {job.get('worker_id') or 'pending'})"
                for job in jobs
            )
        return "\n".join(lines)

    if role != "admin":
        store.record_event("deployment.chat.command.denied", deployment_id, {
            "actor": actor, "role": role, "action": action,
        })
        return "This action requires the **admin** role. An operator can create plans, but only an admin can approve or execute infrastructure changes."

    if action in ("approve", "approve_deploy"):
        try:
            approved = _approve_saved_plan(deployment_id, actor, "web-chat")
        except HTTPException as exc:
            return f"**Approval not completed:** {exc.detail}"
        fingerprint = approved["plan"].get("iac_bundle", {}).get("fingerprint", "")
        store.record_event("deployment.chat.approved", deployment_id, {
            "actor": actor, "iac_fingerprint": fingerprint,
        })
        if action == "approve":
            return (
                f"**Deployment approved.** The saved IaC bundle {fingerprint[:16]} is approved. "
                "No resources have been changed yet. Say **deploy** when you are ready to execute it."
            )

    try:
        result = _execute_approved_plan(deployment_id, actor, "web-chat")
    except HTTPException as exc:
        return f"**Execution not started:** {exc.detail}"
    state["phase"] = "deployment_running"
    state["deployment_id"] = deployment_id
    store.set_state(session_id, state)
    lines = [
        "**The Carpenter has accepted the deployment and queued the provider work.**",
        f"- Deployment: {deployment_id}",
        f"- Status: {result['status']}",
        f"- IaC fingerprint: {result.get('iac_fingerprint', '')}",
        f"- FaaS jobs queued: {len(result['jobs'])}",
    ]
    lines.extend(f"- {job['component']} -> {job['function_name']} on {job.get('target_worker_id') or 'eligible worker'}" for job in result["jobs"])
    lines.append("Say **status** to follow the worker results. Provisioning is asynchronous; queued does not mean the resources are already ready.")
    return "\n".join(lines)



@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "the-carpenter", "version": "0.4.0"}


@app.get("/api/v1/functions")
def function_catalogue() -> dict[str, object]:
    return {
        "runtime": "python-native-distributed-faas",
        "functions": store.list_functions(),
        "local_functions": orchestrator.function_catalogue(),
    }


@app.get("/api/v1/inventory")
def inventory(x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token")) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    nodes = store.list_agents(online_only=False)
    return {
        "online": [node for node in nodes if node.get("online")],
        "offline": [node for node in nodes if not node.get("online")],
        "online_count": sum(1 for node in nodes if node.get("online")),
        "total_enrolled": len(nodes),
    }


@app.post("/api/v1/agents/heartbeat")
def agent_heartbeat(
    heartbeat: AgentHeartbeat,
    x_agent_token: str = Header(default="", alias="X-Agent-Token"),
) -> dict[str, object]:
    _require_agent(x_agent_token)
    store.upsert_agent(heartbeat.model_dump(mode="json"))
    return {"accepted": True, "node_id": heartbeat.node_id}


@app.post("/api/v1/jobs")
def enqueue_job(
    request: JobEnqueueRequest,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    try:
        job = store.enqueue_job(
            request.function_name, request.function_version, request.payload,
            request.max_attempts, request.priority, request.idempotency_key, request.target_worker_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store.record_event("faas.job.enqueued", job["job_id"], {
        "function_name": request.function_name, "version": request.function_version,
    })
    return job


@app.get("/api/v1/jobs")
def list_jobs(
    limit: int = 100,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return {"jobs": store.list_jobs(limit)}


@app.get("/api/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/api/v1/workers/{worker_id}/claim")
def worker_claim(
    worker_id: str,
    x_agent_token: str = Header(default="", alias="X-Agent-Token"),
) -> dict[str, Any] | None:
    _require_agent(x_agent_token)
    agent = store.get_agent(worker_id)
    if not agent or not agent.get("online"):
        raise HTTPException(status_code=409, detail="Worker has no fresh heartbeat.")
    job = store.claim_job(worker_id, settings.worker_lease_seconds)
    return job


@app.post("/api/v1/workers/{worker_id}/jobs/{job_id}/complete")
def worker_complete(
    worker_id: str,
    job_id: str,
    request: JobResultRequest,
    x_agent_token: str = Header(default="", alias="X-Agent-Token"),
) -> dict[str, bool]:
    _require_agent(x_agent_token)
    job = store.get_job(job_id)
    accepted = store.complete_job(job_id, worker_id, request.lease_token, request.result)
    if not accepted:
        raise HTTPException(status_code=409, detail="Job lease is invalid or expired.")
    if job and job["function_name"].startswith("discovery."):
        store.merge_agent_discovery(worker_id, job["function_name"], request.result)
    store.record_event("faas.job.succeeded", job_id, {"worker_id": worker_id})
    if job and job.get("payload", {}).get("deployment_id"):
        reconcile_deployment_status(job["payload"]["deployment_id"])
    return {"accepted": True}


@app.post("/api/v1/workers/{worker_id}/jobs/{job_id}/fail")
def worker_fail(
    worker_id: str,
    job_id: str,
    request: JobFailureRequest,
    x_agent_token: str = Header(default="", alias="X-Agent-Token"),
) -> dict[str, bool]:
    _require_agent(x_agent_token)
    accepted = store.fail_job(job_id, worker_id, request.lease_token, request.error)
    if not accepted:
        raise HTTPException(status_code=409, detail="Job lease is invalid or expired.")
    store.record_event("faas.job.failed", job_id, {"worker_id": worker_id, "error": request.error})
    job = store.get_job(job_id)
    if job and job.get("payload", {}).get("deployment_id"):
        reconcile_deployment_status(job["payload"]["deployment_id"])
    return {"accepted": True}


@app.post("/api/v1/discovery/scan")
def schedule_discovery(
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    jobs = []
    workers = store.list_agents(online_only=True)
    for worker in workers:
        for function_name in (
            "discovery.host_inventory",
            "discovery.hypervisor_probe",
            "discovery.storage_network",
        ):
            jobs.append(store.enqueue_job(
                function_name, "1.0.0", {}, max_attempts=3,
                idempotency_key=f"discovery-{worker['node_id']}-{function_name}-{uuid.uuid4()}",
                target_worker_id=worker["node_id"],
            ))
    store.record_event("discovery.scan.queued", None, {"job_ids": [job["job_id"] for job in jobs]})
    return {"jobs": jobs, "worker_count": len(workers),
            "message": "Discovery functions were queued against every online enrolled node."}


@app.post("/api/v1/resources/plan")
def resource_plan(
    request: DeploymentPlanInput,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    hosts = store.list_agents(online_only=True)
    return plan_placement(
        hosts, request.vm_count, request.vcpu_per_vm, request.memory_gb_per_vm,
        request.disk_gb_per_vm, request.high_availability,
    )


@app.post("/api/v1/resources/forecast")
def resource_forecast(
    samples: list[dict[str, float]],
    threshold_percent: float = 80.0,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return forecast_capacity(samples, threshold_percent)


@app.post("/api/v1/operations/failover-plan")
def operations_failover_plan(
    body: dict[str, Any],
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    failed_node_id = str(body.get("failed_node_id", ""))
    if not failed_node_id:
        raise HTTPException(status_code=422, detail="failed_node_id is required")
    try:
        result = build_failover_plan(
            store.list_agents(online_only=True),
            failed_node_id=failed_node_id,
            vm_count=int(body.get("vm_count", 1)),
            vcpu_per_vm=int(body.get("vcpu_per_vm", 2)),
            memory_gb_per_vm=int(body.get("memory_gb_per_vm", 4)),
            disk_gb_per_vm=int(body.get("disk_gb_per_vm", 40)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.record_event("operations.failover.plan.created", failed_node_id, result)
    return result


@app.post("/api/v1/operations/load-balancer/plan")
def operations_load_balancer_plan(
    body: dict[str, Any],
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    try:
        result = load_balancer_plan(
            body.get("backends", []), int(body.get("frontend_port", 80))
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.record_event("operations.load-balancer.plan.created", None, {
        "backend_count": result["backend_count"],
    })
    return result


@app.get("/api/v1/operations/metrics")
def operations_metrics(
    limit: int = 100,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    jobs = [
        job for job in store.list_jobs(limit)
        if job["function_name"] == "operations.metrics_snapshot"
        and job["status"] == "succeeded"
    ]
    return {"snapshots": [
        {"job_id": job["job_id"], "worker_id": job["worker_id"],
         "captured": job["updated_at"], "metrics": job["result"]}
        for job in jobs
    ]}


@app.get("/api/v1/operations/events")
def operation_events(
    limit: int = 100,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return {"events": store.list_events(limit)}


@app.post("/api/v1/deployments/plan")
def create_deployment_plan(
    request: DeploymentRequest,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    hosts = store.list_agents(online_only=True)
    plan = DeploymentEngine().build_plan(request.model_dump(), hosts)
    record = create_deployment_record(request.destination, request.service_model, plan)
    store.record_event("deployment.plan.created", record["deployment_id"], {
        "destination": request.destination,
        "service_model": request.service_model,
        "ready_to_execute": plan["ready_to_execute_after_approval"],
    })
    return record


@app.get("/api/v1/deployments/{deployment_id}")
def get_deployment(
    deployment_id: str,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    record = reconcile_deployment_status(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment plan not found")
    return record


@app.get("/api/v1/deployments/{deployment_id}/iac")
def get_deployment_iac(
    deployment_id: str,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    record = get_deployment_record(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment not found")
    bundle = record["plan"].get("iac_bundle")
    if not isinstance(bundle, dict):
        raise HTTPException(status_code=404, detail="Generated IaC bundle not found")
    try:
        validation = validate_iac_bundle(bundle)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=f"Stored IaC validation failed: {exc}") from exc
    return {
        "deployment_id": deployment_id,
        "fingerprint": bundle["fingerprint"],
        "validation": validation,
        "resource_graph": bundle["resources"],
        "artifacts": bundle["artifacts"],
    }


@app.post("/api/v1/deployments/{deployment_id}/approve")
def approve_deployment(
    deployment_id: str,
    request: DeploymentApproval,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    # Do not trust a caller-supplied approved_by value as an identity claim.
    return _approve_saved_plan(deployment_id, "api-admin", "admin-api")


@app.post("/api/v1/deployments/{deployment_id}/execute")
def execute_deployment(
    deployment_id: str,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return _execute_approved_plan(deployment_id, "api-admin", "admin-api")


@app.post("/api/v1/operations/ha-assessment")
def ha_assessment(
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return assess_high_availability(store.list_agents(online_only=True))


@app.post("/api/v1/operations/recommendation")
def operations_recommendation(
    body: dict[str, Any],
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    result = recommend_action(body.get("metrics", {}), body.get("policy", {}))
    store.record_event("operations.recommendation.created", None, result)
    return result


@app.post("/api/v1/operations/metrics/collect")
def collect_metrics(
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    workers = store.list_agents(online_only=True)
    jobs = [
        store.enqueue_job(
            "operations.metrics_snapshot", "1.0.0", {},
            max_attempts=3, idempotency_key=f"metrics-{node['node_id']}-{uuid.uuid4()}",
            target_worker_id=node["node_id"],
        )
        for node in workers
        if node.get("capabilities", {}).get("operations.metrics_snapshot") == "1.0.0"
    ]
    store.record_event("operations.metrics.queued", None, {"job_ids": [job["job_id"] for job in jobs]})
    return {"jobs": jobs, "worker_count": len(jobs)}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    if _web_identity(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"app_name": settings.app_name, "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, token: str = Form(...)) -> Response:
    issued = issue_session(token)
    if not issued:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"app_name": settings.app_name, "error": "The supplied credential was not accepted."},
            status_code=401,
        )
    identity, cookie_value = issued
    store.record_event("web.session.created", None, {
        "subject": identity["subject"], "role": identity["role"],
    })
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME, cookie_value, httponly=True, secure=settings.cookie_secure,
        samesite="strict", max_age=SESSION_TTL_SECONDS,
    )
    # Remove the legacy unsigned conversation cookie from older sessions.
    response.delete_cookie("carpenter_session", httponly=True, secure=settings.cookie_secure, samesite="strict")
    return response


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)) -> RedirectResponse:
    identity = _web_identity(request)
    if not identity or not verify_csrf(identity, csrf_token):
        raise HTTPException(status_code=403, detail="The session or CSRF token is invalid.")
    store.record_event("web.session.closed", None, {
        "subject": identity["subject"], "role": identity["role"],
    })
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, httponly=True, secure=settings.cookie_secure, samesite="strict")
    response.delete_cookie("carpenter_session", httponly=True, secure=settings.cookie_secure, samesite="strict")
    return response


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    identity = _web_identity(request)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    session_id = _conversation_id(identity)
    messages = store.list_messages(session_id)
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "messages": messages,
            "agent_count": len(store.list_agents()),
            "identity": identity,
            "csrf_token": identity["csrf"],
            "can_prompt": identity["role"] in ("operator", "admin"),
        },
    )
    return response


@app.post("/prompt")
def prompt(
    request: Request,
    message: str = Form(...),
    csrf_token: str = Form(...),
) -> RedirectResponse:
    identity = _web_identity(request)
    if not identity:
        return RedirectResponse("/login", status_code=303)
    if identity["role"] not in ("operator", "admin"):
        raise HTTPException(status_code=403, detail="The viewer role cannot submit prompts.")
    if not verify_csrf(identity, csrf_token):
        raise HTTPException(status_code=403, detail="The CSRF token is invalid.")
    content = message.strip()
    if not content:
        return RedirectResponse("/", status_code=303)
    if len(content) > 8000:
        raise HTTPException(status_code=413, detail="Prompt is too long.")
    session_id = _conversation_id(request)
    store.add_message(session_id, "user", content)
    answer = _handle_chat_deployment_command(session_id, identity, content)
    if answer is None:
        answer = orchestrator.respond(session_id, content)
    store.add_message(session_id, "assistant", answer)
    response = RedirectResponse("/", status_code=303)
    return response
