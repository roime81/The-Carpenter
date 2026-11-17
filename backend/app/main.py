from __future__ import annotations

import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import store
from app.config import settings
from app.models import AgentHeartbeat
from app.orchestrator import CarpenterOrchestrator

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(
    title="The Carpenter",
    description="A prompt-driven Python cloud control plane.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
orchestrator = CarpenterOrchestrator()


@app.on_event("startup")
def startup() -> None:
    store.initialise_store()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "the-carpenter"}


@app.get("/api/v1/functions")
def function_catalogue() -> dict[str, object]:
    return {"runtime": "python-native-faas-local", "functions": orchestrator.function_catalogue()}


@app.post("/api/v1/agents/heartbeat")
def agent_heartbeat(
    heartbeat: AgentHeartbeat,
    x_agent_token: str = Header(default="", alias="X-Agent-Token"),
) -> dict[str, object]:
    expected = settings.agent_enrollment_token
    if not expected:
        raise HTTPException(status_code=503, detail="Node enrollment is disabled: configure an agent token.")
    if not secrets.compare_digest(x_agent_token, expected):
        raise HTTPException(status_code=401, detail="Invalid node enrollment token.")
    store.upsert_agent(heartbeat.model_dump(mode="json"))
    return {"accepted": True, "node_id": heartbeat.node_id}


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
        "carpenter_session",
        session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
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
        "carpenter_session",
        session_id,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response
