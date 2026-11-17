from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

import psutil

from handlers import installed_capabilities, hypervisor_probe, execute

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("carpenter-node")


def inventory() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    addresses: set[str] = set()
    interfaces = psutil.net_if_addrs()
    for addrs in interfaces.values():
        for address in addrs:
            if address.family == socket.AF_INET and not address.address.startswith("127."):
                addresses.add(address.address)

    stable_name = socket.getfqdn() or socket.gethostname()
    node_id = os.getenv("CARPENTER_NODE_ID") or str(uuid.uuid5(uuid.NAMESPACE_DNS, stable_name))
    return {
        "node_id": node_id,
        "hostname": socket.gethostname(),
        "operating_system": __import__("platform").platform(),
        "architecture": __import__("platform").machine(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "memory_total_bytes": memory.total,
        "memory_available_bytes": memory.available,
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "ipv4_addresses": sorted(addresses),
        "capabilities": installed_capabilities(),
        "discovery": {"hypervisor": hypervisor_probe({})},
        "failure_domain": os.getenv("CARPENTER_FAILURE_DOMAIN", "default"),
    }


def request_json(url: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Agent-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            content = response.read()
            if not content:
                return None
            return json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 204:
            return None
        message = exc.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(f"Control plane returned HTTP {exc.code}: {message}") from exc


def send_heartbeat(base_url: str, token: str, node: dict[str, Any]) -> None:
    result = request_json(
        base_url.rstrip("/") + "/api/v1/agents/heartbeat", token, node
    )
    if not result or not result.get("accepted"):
        raise RuntimeError("Control plane did not accept node heartbeat")
    logger.info("Heartbeat accepted: %s (%s)", node["hostname"], node["node_id"])


def claim_job(base_url: str, token: str, node_id: str) -> dict[str, Any] | None:
    return request_json(
        base_url.rstrip("/") + f"/api/v1/workers/{node_id}/claim",
        token,
        {},
    )


def report_success(
    base_url: str, token: str, node_id: str, job_id: str,
    lease_token: str, result: dict[str, Any],
) -> None:
    request_json(
        base_url.rstrip("/") + f"/api/v1/workers/{node_id}/jobs/{job_id}/complete",
        token,
        {"lease_token": lease_token, "result": result},
    )


def report_failure(
    base_url: str, token: str, node_id: str, job_id: str,
    lease_token: str, error: str,
) -> None:
    request_json(
        base_url.rstrip("/") + f"/api/v1/workers/{node_id}/jobs/{job_id}/fail",
        token,
        {"lease_token": lease_token, "error": error[:4000]},
    )


def process_job(base_url: str, token: str, node_id: str, job: dict[str, Any]) -> None:
    job_id = job["job_id"]
    lease_token = job["lease_token"]
    try:
        output = execute(
            job["function_name"], job["function_version"], job.get("payload", {})
        )
        report_success(base_url, token, node_id, job_id, lease_token, output)
        logger.info("Completed FaaS job %s (%s)", job_id, job["function_name"])
    except Exception as exc:
        logger.exception("FaaS job failed: %s", job_id)
        try:
            report_failure(base_url, token, node_id, job_id, lease_token, str(exc))
        except Exception:
            logger.exception("Unable to report FaaS failure for job %s", job_id)


def main() -> None:
    base_url = os.environ["CARPENTER_URL"].rstrip("/")
    token = os.environ["CARPENTER_AGENT_TOKEN"]
    heartbeat_seconds = max(15, int(os.getenv("CARPENTER_HEARTBEAT_SECONDS", "30")))
    poll_seconds = max(1, float(os.getenv("CARPENTER_WORKER_POLL_SECONDS", "2")))
    node = inventory()
    node_id = node["node_id"]
    logger.info("Starting Carpenter worker %s at %s", node_id, base_url)

    stop = threading.Event()
    registered = threading.Event()

    def heartbeat_loop() -> None:
        while not stop.is_set():
            try:
                current = inventory()
                send_heartbeat(base_url, token, current)
                registered.set()
            except Exception as exc:
                registered.clear()
                logger.warning("Heartbeat failed: %s", exc)
            if stop.wait(heartbeat_seconds):
                break

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        name="carpenter-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        while not stop.is_set():
            if not registered.is_set():
                time.sleep(poll_seconds)
                continue
            try:
                job = claim_job(base_url, token, node_id)
                if job:
                    # The independent heartbeat thread keeps this worker visible
                    # while a hypervisor or platform function is running.
                    process_job(base_url, token, node_id, job)
                else:
                    time.sleep(poll_seconds)
            except Exception as exc:
                registered.clear()
                logger.warning("Worker poll failed; waiting for heartbeat recovery: %s", exc)
                time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Stopping Carpenter worker")
    finally:
        stop.set()
        heartbeat_thread.join(timeout=heartbeat_seconds + 2)


if __name__ == "__main__":
    main()
