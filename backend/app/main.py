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
            request.max_attempts, request.priority, request.idempotency_key,
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
    for function_name in (
        "discovery.host_inventory",
        "discovery.hypervisor_probe",
        "discovery.storage_network",
    ):
        jobs.append(store.enqueue_job(
            function_name, "1.0.0", {}, max_attempts=3,
            idempotency_key=f"discovery-{function_name}-{uuid.uuid4()}",
        ))
    store.record_event("discovery.scan.queued", None, {"job_ids": [job["job_id"] for job in jobs]})
    return {"jobs": jobs, "message": "Discovery functions were queued for enrolled workers."}


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


@app.get("/api/v1/operations/events")
def operation_events(
    limit: int = 100,
    x_carpenter_token: str = Header(default="", alias="X-Carpenter-Token"),
) -> dict[str, Any]:
    _require_admin(x_carpenter_token)
    return {"events": store.list_events(limit)}


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
