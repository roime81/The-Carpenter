from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any


class ProxmoxError(RuntimeError):
    pass


class ProxmoxAdapter:
    """Proxmox VE API adapter. Never disables TLS verification.

    This adapter clones a pre-created, cloud-init-capable template. It does not
    invent or download OS images. VM creation must be called only after plan
    approval and a successful dry-run.
    """

    def __init__(
        self, base_url: str, token_id: str, token_secret: str,
        verify_tls: bool = True, timeout: int = 20,
    ) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("Proxmox API URL must use HTTPS")
        if not token_id or not token_secret:
            raise ValueError("Proxmox API token credentials are required")
        self.base_url = base_url.rstrip("/")
        self.authorization = f"PVEAPIToken={token_id}={token_secret}"
        self.context = ssl.create_default_context() if verify_tls else None
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

    def clone_vm(
        self, node: str, template_vmid: int, new_vmid: int, name: str,
        cores: int, memory_mb: int, full_clone: bool = True,
    ) -> dict[str, Any]:
        if template_vmid <= 0 or new_vmid <= 0 or cores < 1 or memory_mb < 512:
            raise ValueError("Invalid VM or template sizing")
        clone = self._request(
            "POST",
            f"/nodes/{urllib.parse.quote(node)}/qemu/{template_vmid}/clone",
            {"newid": new_vmid, "name": name, "full": 1 if full_clone else 0},
        )
        config = self._request(
            "POST",
            f"/nodes/{urllib.parse.quote(node)}/qemu/{new_vmid}/config",
            {"cores": cores, "memory": memory_mb},
        )
        return {"clone_task": clone, "config_task": config, "vmid": new_vmid, "name": name}

    def start_vm(self, node: str, vmid: int) -> Any:
        return self._request("POST", f"/nodes/{urllib.parse.quote(node)}/qemu/{vmid}/status/start", {})
