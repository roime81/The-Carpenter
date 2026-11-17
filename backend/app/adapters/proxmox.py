from __future__ import annotations

import json
import ssl
import time
import urllib.parse
import urllib.request
from typing import Any


class ProxmoxError(RuntimeError):
    pass


class ProxmoxAdapter:
    """Proxmox VE API adapter. TLS verification is always enabled.

    This adapter clones a pre-created, cloud-init-capable template. It does not
    invent or download OS images. Call it only after plan approval and a dry-run.
    """

    def __init__(
        self, base_url: str, token_id: str, token_secret: str, timeout: int = 20,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("Proxmox API URL must use HTTPS")
        if not token_id or not token_secret:
            raise ValueError("Proxmox API token credentials are required")
        self.base_url = base_url.rstrip("/")
        self.authorization = f"PVEAPIToken={token_id}={token_secret}"
        self.context = ssl.create_default_context()
        self.timeout = timeout

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        body = urllib.parse.urlencode(data or {}).encode() if data is not None else None
        request = urllib.request.Request(
            self.base_url + "/api2/json" + path,
            data=body,
            headers={
                "Authorization": self.authorization,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProxmoxError(f"Proxmox API request failed: {type(exc).__name__}") from exc
        return payload.get("data")

    def next_vmid(self) -> int:
        value = self._request("GET", "/cluster/nextid")
        vmid = int(value)
        if not 100 <= vmid <= 999999999:
            raise ProxmoxError("Proxmox returned an invalid next VM identifier")
        return vmid

    def wait_for_task(self, node: str, upid: str, timeout_seconds: int = 180) -> dict[str, Any]:
        encoded = urllib.parse.quote(upid, safe="")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self._request(
                "GET",
                f"/nodes/{urllib.parse.quote(node, safe='')}/tasks/{encoded}/status",
            )
            if isinstance(status, dict) and status.get("status") == "stopped":
                if status.get("exitstatus") != "OK":
                    raise ProxmoxError(f"Proxmox task ended with status {status.get('exitstatus')}")
                return status
            time.sleep(2)
        raise TimeoutError("Proxmox task did not complete before the timeout")

    def _wait_if_task(self, node: str, task: Any) -> None:
        if isinstance(task, str) and task.startswith("UPID:"):
            self.wait_for_task(node, task)

    def clone_vm(
        self, node: str, template_vmid: int, new_vmid: int, name: str,
        cores: int, memory_mb: int, full_clone: bool = True,
    ) -> dict[str, Any]:
        if template_vmid <= 0 or new_vmid <= 0 or cores < 1 or memory_mb < 512:
            raise ValueError("Invalid VM or template sizing")
        encoded_node = urllib.parse.quote(node, safe="")
        clone = self._request(
            "POST",
            f"/nodes/{encoded_node}/qemu/{template_vmid}/clone",
            {"newid": new_vmid, "name": name, "full": 1 if full_clone else 0},
        )
        self._wait_if_task(node, clone)
        config = self._request(
            "POST",
            f"/nodes/{encoded_node}/qemu/{new_vmid}/config",
            {"cores": cores, "memory": memory_mb},
        )
        self._wait_if_task(node, config)
        return {"clone_task": clone, "config_task": config, "vmid": new_vmid, "name": name}

    def start_vm(self, node: str, vmid: int) -> Any:
        task = self._request(
            "POST",
            f"/nodes/{urllib.parse.quote(node, safe='')}/qemu/{vmid}/status/start",
            {},
        )
        self._wait_if_task(node, task)
        return task
