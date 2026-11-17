from __future__ import annotations

import json
import logging
import os
import platform
import socket
import time
import urllib.error
import urllib.request
import uuid

import psutil

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("carpenter-node")


def inventory() -> dict[str, object]:
    root = os.path.abspath(os.sep)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(root)
    addresses: set[str] = set()
    for interfaces in psutil.net_if_addrs().values():
        for address in interfaces:
            if address.family == socket.AF_INET and not address.address.startswith("127."):
                addresses.add(address.address)

    stable_name = socket.getfqdn() or socket.gethostname()
    node_id = os.getenv("CARPENTER_NODE_ID") or str(uuid.uuid5(uuid.NAMESPACE_DNS, stable_name))
    return {
        "node_id": node_id,
        "hostname": socket.gethostname(),
        "operating_system": platform.platform(),
        "architecture": platform.machine(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "memory_total_bytes": memory.total,
        "memory_available_bytes": memory.available,
        "disk_total_bytes": disk.total,
        "disk_free_bytes": disk.free,
        "ipv4_addresses": sorted(addresses),
    }


def send_heartbeat(url: str, token: str) -> None:
    payload = json.dumps(inventory()).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/api/v1/agents/heartbeat",
        data=payload,
        headers={"Content-Type": "application/json", "X-Agent-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise RuntimeError(f"Unexpected control-plane response: HTTP {response.status}")
        logger.info("Heartbeat accepted: %s", socket.gethostname())


def main() -> None:
    control_plane = os.environ["CARPENTER_URL"]
    token = os.environ["CARPENTER_AGENT_TOKEN"]
    interval = max(15, int(os.getenv("CARPENTER_HEARTBEAT_SECONDS", "30")))
    logger.info("Starting Carpenter node agent for %s", control_plane)

    while True:
        try:
            send_heartbeat(control_plane, token)
        except (urllib.error.URLError, TimeoutError, RuntimeError, KeyError) as exc:
            logger.warning("Heartbeat failed: %s", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
