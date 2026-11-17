from __future__ import annotations

import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
from app.deployment_store import create as create_deployment_record, get as get_deployment_record, approve as approve_deployment_record, set_status as set_deployment_status
from app.deployment_engine import DeploymentEngine
from app.operations_engine import assess_high_availability, recommend_action, build_failover_plan, load_balancer_plan

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title="The Carpenter",
    description="A prompt-driven Python cloud control plane.",
    version="0.2.0",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "the-carpenter", "version": "0.2.0"}


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
    accepted = store.complete_job(job_id, worker_id, request.lease_token, request.result)
    if not accepted:
        raise HTTPException(status_code=409, detail="Job lease is invalid or expired.")
    store.record_event("faas.job.succeeded", job_id, {"worker_id": worker_id})
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
    record = get_deployment_record(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment plan not found")
    return record


@app.post("/api/v1/deployments/{deployment_id}/approve")
def approve_deployment(
    deployment_id: str,
    request: DeploymentApproval,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    record = approve_deployment_record(deployment_id, request.approved_by)
    if not record:
        raise HTTPException(status_code=409, detail="Only a planned deployment can be approved.")
    return record


@app.post("/api/v1/deployments/{deployment_id}/execute")
def execute_deployment(
    deployment_id: str,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    record = get_deployment_record(deployment_id)
    if not record:
        raise HTTPException(status_code=404, detail="Deployment not found")
    if record["status"] != "approved":
        raise HTTPException(status_code=409, detail="Deployment must be approved before execution.")
    if not record["plan"].get("ready_to_execute_after_approval"):
        raise HTTPException(status_code=409, detail="Deployment plan failed capacity, HA, or adapter readiness checks.")
    set_deployment_status(deployment_id, "executing")
    store.record_event("deployment.execution.started", deployment_id, {"destination": record["destination"]})
    try:
        result = DeploymentEngine().execute(deployment_id, record["plan"])
        set_deployment_status(deployment_id, "succeeded")
        store.record_event("deployment.execution.succeeded", deployment_id, result)
        return {"deployment_id": deployment_id, "status": "succeeded", "result": result}
    except Exception as exc:
        set_deployment_status(deployment_id, "failed")
        store.record_event("deployment.execution.failed", deployment_id, {"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Deployment adapter failed: {type(exc).__name__}: {exc}") from exc


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


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    session_id = request.cookies.get("carpenter_session") or str(uuid.uuid4())
    messages = store.list_messages(session_id)
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "messages": messages,
            "agent_count": len(store.list_agents()),
        },
    )
    response.set_cookie(
        "carpenter_session", session_id, httponly=True,
        secure=settings.cookie_secure, samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return response


@app.post("/prompt")
def prompt(request: Request, message: str = Form(...)) -> RedirectResponse:
    content = message.strip()
    if not content:
        return RedirectResponse("/", status_code=303)
    if len(content) > 8000:
        raise HTTPException(status_code=413, detail="Prompt is too long.")
    session_id = request.cookies.get("carpenter_session") or str(uuid.uuid4())
    store.add_message(session_id, "user", content)
    answer = orchestrator.respond(session_id, content)
    store.add_message(session_id, "assistant", answer)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        "carpenter_session", session_id, httponly=True,
        secure=settings.cookie_secure, samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return response
