from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import psutil


BASE_FUNCTION_VERSIONS = {
    "discovery.host_inventory": "1.0.0",
    "discovery.hypervisor_probe": "1.0.0",
    "discovery.storage_network": "1.0.0",
    "operations.metrics_snapshot": "1.0.0",
    "network.tcp_probe": "1.0.0",
}
SAFE_TCP_PORTS = {22, 80, 443, 6443, 8006, 8080, 8443, 9090, 9100, 9443}


def installed_capabilities() -> dict[str, str]:
    """Advertise provider functions only when that worker has local credentials/config."""
    result = dict(BASE_FUNCTION_VERSIONS)
    if all(os.getenv(key) for key in (
        "CARPENTER_PROXMOX_URL", "CARPENTER_PROXMOX_TOKEN_ID",
        "CARPENTER_PROXMOX_TOKEN_SECRET", "CARPENTER_PROXMOX_NODE",
        "CARPENTER_PROXMOX_TEMPLATE_VMID",
    )):
        result["compute.proxmox_deploy"] = "1.0.0"
    if os.getenv("CARPENTER_KUBERNETES_API_URL") and os.getenv("CARPENTER_KUBERNETES_TOKEN"):
        result["platform.kubernetes_deploy"] = "1.0.0"
    if os.getenv("CARPENTER_GAMGEE_INSTALLER_URL") and os.getenv("CARPENTER_GAMGEE_INSTALLER_TOKEN"):
        result["gamgee.bootstrap"] = "1.0.0"
    return result


def _root_path() -> str:
    return os.path.abspath(os.sep)


def _inventory() -> dict[str, Any]:
    root_usage = psutil.disk_usage(_root_path())
    return {
        "hostname": socket.gethostname(),
        "operating_system": __import__("platform").platform(),
        "architecture": __import__("platform").machine(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory_total_bytes": psutil.virtual_memory().total,
        "memory_available_bytes": psutil.virtual_memory().available,
        "disk_total_bytes": root_usage.total,
        "disk_free_bytes": root_usage.free,
    }


def host_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    return _inventory()


def hypervisor_probe(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "kvm_device": Path("/dev/kvm").exists(),
        "libvirt_socket": Path("/run/libvirt/libvirt-sock").exists()
            or Path("/var/run/libvirt/libvirt-sock").exists(),
        "libvirt_cli": shutil.which("virsh") is not None,
        "proxmox_host": Path("/etc/pve").exists(),
        "container_runtimes": {
            "docker": shutil.which("docker") is not None,
            "podman": shutil.which("podman") is not None,
            "containerd": shutil.which("ctr") is not None,
        },
        "kubernetes_tools": {
            "kubectl": shutil.which("kubectl") is not None,
            "kubelet": shutil.which("kubelet") is not None,
        },
        "note": "Presence checks only; no privileged commands or configuration changes were executed.",
    }


def storage_network(payload: dict[str, Any]) -> dict[str, Any]:
    partitions = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "filesystem": part.fstype,
                "total_bytes": usage.total,
                "free_bytes": usage.free,
            })
        except (PermissionError, OSError):
            continue

    interfaces = {}
    addresses = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    for name, addrs in addresses.items():
        interfaces[name] = {
            "is_up": bool(stats[name].isup) if name in stats else False,
            "speed_mbps": stats[name].speed if name in stats else 0,
            "addresses": [
                {"family": str(item.family), "address": item.address, "netmask": item.netmask}
                for item in addrs
            ],
        }
    return {
        "partitions": partitions,
        "interfaces": interfaces,
        "network_counters": psutil.net_io_counters()._asdict(),
    }


def metrics_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    virtual = psutil.virtual_memory()
    disk = psutil.disk_usage(_root_path())
    network = psutil.net_io_counters()
    return {
        "captured_at_epoch": time.time(),
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "memory_percent": virtual.percent,
        "memory_available_bytes": virtual.available,
        "root_disk_percent": disk.percent,
        "network_bytes_sent": network.bytes_sent,
        "network_bytes_received": network.bytes_recv,
        "load_average": list(psutil.getloadavg()) if hasattr(psutil, "getloadavg") else None,
    }


def tcp_probe(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("target", "")).strip()
    ports = payload.get("ports", [])
    try:
        address = ipaddress.ip_address(target)
    except ValueError as exc:
        raise ValueError("TCP discovery requires a literal IP address; DNS and CIDR sweeps are disabled.") from exc
    if not address.is_private and not address.is_loopback and not address.is_link_local:
        raise ValueError("Only explicitly supplied private, loopback, or link-local IP targets are allowed.")
    if not isinstance(ports, list) or not ports or len(ports) > 16:
        raise ValueError("Supply between 1 and 16 explicit TCP ports.")
    validated = []
    for port in ports:
        if not isinstance(port, int) or port not in SAFE_TCP_PORTS:
            raise ValueError(f"Port {port!r} is not in the Carpenter discovery allow-list.")
        validated.append(port)

    results = []
    for port in sorted(set(validated)):
        started = time.monotonic()
        try:
            with socket.create_connection((str(address), port), timeout=1.5):
                results.append({"port": port, "reachable": True,
                                "latency_ms": round((time.monotonic() - started) * 1000, 2)})
        except OSError:
            results.append({"port": port, "reachable": False, "latency_ms": None})
    return {"target": str(address), "results": results}


# Provider adapters execute on the selected worker, not inside the web/API process.

def _proxmox_request(
    method: str, path: str, data: dict[str, Any] | None = None,
) -> Any:
    base_url = os.environ["CARPENTER_PROXMOX_URL"].rstrip("/")
    token_id = os.environ["CARPENTER_PROXMOX_TOKEN_ID"]
    token_secret = os.environ["CARPENTER_PROXMOX_TOKEN_SECRET"]
    if not base_url.startswith("https://"):
        raise ValueError("Proxmox API URL must use HTTPS")
    body = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    request = urllib.request.Request(
        base_url + "/api2/json" + path,
        data=body,
        headers={
            "Authorization": f"PVEAPIToken={token_id}={token_secret}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context(), timeout=30
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Proxmox worker API call failed: {type(exc).__name__}") from exc
    return payload.get("data")


def _wait_proxmox_task(node: str, task: Any, timeout_seconds: int = 120) -> None:
    if not isinstance(task, str) or not task.startswith("UPID:"):
        return
    deadline = time.monotonic() + timeout_seconds
    encoded_task = urllib.parse.quote(task, safe="")
    encoded_node = urllib.parse.quote(node, safe="")
    while time.monotonic() < deadline:
        status = _proxmox_request(
            "GET", f"/nodes/{encoded_node}/tasks/{encoded_task}/status"
        )
        if isinstance(status, dict) and status.get("status") == "stopped":
            if status.get("exitstatus") != "OK":
                raise RuntimeError(f"Proxmox task failed: {status.get('exitstatus')}")
            return
        time.sleep(2)
    raise TimeoutError("Proxmox task did not finish before the worker timeout")


def proxmox_deploy(payload: dict[str, Any]) -> dict[str, Any]:
    deployment_id = str(payload.get("deployment_id", ""))
    vm_definitions = payload.get("vms", [])
    node = os.environ["CARPENTER_PROXMOX_NODE"]
    template_vmid = int(os.environ["CARPENTER_PROXMOX_TEMPLATE_VMID"])
    if not re.fullmatch(r"[a-f0-9-]{16,64}", deployment_id):
        raise ValueError("A valid Carpenter deployment ID is required")
    if not isinstance(vm_definitions, list) or not 1 <= len(vm_definitions) <= 256:
        raise ValueError("A Proxmox worker job must contain between 1 and 256 VM definitions")
    if template_vmid <= 0:
        raise ValueError("CARPENTER_PROXMOX_TEMPLATE_VMID must be a prepared cloud-init template")

    # Stable names allow a retry to recover a VM created before the previous
    # worker attempt lost its lease or acknowledgement.
    existing = _proxmox_request("GET", "/cluster/resources?type=vm") or []
    results = []
    encoded_node = urllib.parse.quote(node, safe="")
    for vm in vm_definitions:
        name = str(vm.get("name", ""))
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", name):
            raise ValueError("VM names must be 1-63 safe alphanumeric/dot/underscore/hyphen characters")
        cores = int(vm.get("vcpu", 0))
        memory_mb = int(vm.get("memory_gb", 0)) * 1024
        if not 1 <= cores <= 256 or not 512 <= memory_mb <= 4_194_304:
            raise ValueError("VM CPU or memory sizing is out of range")

        match = next((item for item in existing if item.get("name") == name), None)
        if match:
            if match.get("node") != node:
                raise RuntimeError(f"VM name {name} already exists on a different Proxmox node")
            vmid = int(match["vmid"])
            action = "reconciled_existing"
        else:
            vmid = int(_proxmox_request("GET", "/cluster/nextid"))
            if not 100 <= vmid <= 999_999_999:
                raise RuntimeError("Proxmox returned an invalid VM ID")
            clone_task = _proxmox_request(
                "POST",
                f"/nodes/{encoded_node}/qemu/{template_vmid}/clone",
                {"newid": vmid, "name": name, "full": 1},
            )
            _wait_proxmox_task(node, clone_task)
            action = "cloned"

        config_task = _proxmox_request(
            "POST",
            f"/nodes/{encoded_node}/qemu/{vmid}/config",
            {"cores": cores, "memory": memory_mb},
        )
        _wait_proxmox_task(node, config_task)
        start_task = _proxmox_request(
            "POST", f"/nodes/{encoded_node}/qemu/{vmid}/status/start", {}
        )
        _wait_proxmox_task(node, start_task)
        results.append({
            "name": name, "vmid": vmid, "action": action, "status": "started",
        })

    return {
        "deployment_id": deployment_id,
        "node": node,
        "created_or_reconciled": results,
        "execution_status": "succeeded",
    }


def _kubernetes_apply(path: str, body: dict[str, Any]) -> Any:
    api_url = os.environ["CARPENTER_KUBERNETES_API_URL"].rstrip("/")
    token = os.environ["CARPENTER_KUBERNETES_TOKEN"]
    if not api_url.startswith("https://"):
        raise ValueError("Kubernetes API URL must use HTTPS")
    encoded = urllib.parse.urlencode({"fieldManager": "the-carpenter"})
    request = urllib.request.Request(
        api_url + path + "?" + encoded,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/apply-patch+yaml",
            "Accept": "application/json",
        },
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context(), timeout=30
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Kubernetes worker API call failed: {type(exc).__name__}") from exc


def _dns_label(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value))


def kubernetes_deploy(payload: dict[str, Any]) -> dict[str, Any]:
    deployment_id = str(payload.get("deployment_id", ""))
    name = str(payload.get("name", ""))
    namespace = str(payload.get("namespace", "default"))
    image = str(payload.get("container_image", ""))
    replicas = int(payload.get("replicas", 1))
    port = int(payload.get("container_port", 8080))
    if not re.fullmatch(r"[a-f0-9-]{16,64}", deployment_id):
        raise ValueError("A valid Carpenter deployment ID is required")
    if not _dns_label(name) or not _dns_label(namespace):
        raise ValueError("Kubernetes name and namespace must be lowercase DNS labels")
    if not image or len(image) > 512 or any(char.isspace() or ord(char) < 32 for char in image):
        raise ValueError("A valid container image reference is required")
    if not 1 <= replicas <= 100 or not 1 <= port <= 65535:
        raise ValueError("Kubernetes replica count or container port is out of range")

    encoded_namespace = urllib.parse.quote(namespace, safe="")
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace,
                     "labels": {"app.kubernetes.io/managed-by": "the-carpenter",
                                "carpenter.openai.com/deployment-id": deployment_id}},
        "spec": {
            "replicas": replicas,
            "selector": {"matchLabels": {"app": name}},
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {"containers": [{
                    "name": name, "image": image,
                    "ports": [{"containerPort": port}],
                }]},
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "selector": {"app": name},
            "ports": [{"name": "http", "port": port, "targetPort": port, "protocol": "TCP"}],
            "type": "ClusterIP",
        },
    }
    deployment_result = _kubernetes_apply(
        f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments/{name}", deployment
    )
    service_result = _kubernetes_apply(
        f"/api/v1/namespaces/{encoded_namespace}/services/{name}", service
    )
    return {
        "deployment_id": deployment_id,
        "deployment": deployment_result,
        "service": service_result,
        "execution_status": "succeeded",
    }


def gamgee_bootstrap(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.environ["CARPENTER_GAMGEE_INSTALLER_URL"]
    secret = os.environ["CARPENTER_GAMGEE_INSTALLER_TOKEN"].encode("utf-8")
    if not endpoint.startswith("https://"):
        raise ValueError("GAMGEE installer endpoint must use HTTPS")
    deployment_id = str(payload.get("deployment_id", ""))
    if not re.fullmatch(r"[a-f0-9-]{16,64}", deployment_id):
        raise ValueError("A valid Carpenter deployment ID is required")
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Carpenter-Timestamp": timestamp,
            "X-Carpenter-Signature": "sha256=" + signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request, context=ssl.create_default_context(), timeout=60
        ) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"GAMGEE installer worker call failed: {type(exc).__name__}") from exc
    return {"deployment_id": deployment_id, "installer_response": result, "execution_status": "submitted"}


HANDLERS = {
    "discovery.host_inventory": host_inventory,
    "discovery.hypervisor_probe": hypervisor_probe,
    "discovery.storage_network": storage_network,
    "operations.metrics_snapshot": metrics_snapshot,
    "network.tcp_probe": tcp_probe,
    "compute.proxmox_deploy": proxmox_deploy,
    "platform.kubernetes_deploy": kubernetes_deploy,
    "gamgee.bootstrap": gamgee_bootstrap,
}


def execute(function_name: str, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    expected = installed_capabilities().get(function_name)
    handler = HANDLERS.get(function_name)
    if handler is None or expected != version:
        raise ValueError(f"Function is not installed/configured on this worker: {function_name}@{version}")
    result = handler(payload)
    if not isinstance(result, dict):
        raise TypeError("Worker functions must return JSON object results")
    return result
