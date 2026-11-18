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
    if all(os.getenv(key) for key in (
        "CARPENTER_PROXMOX_URL", "CARPENTER_PROXMOX_TOKEN_ID", "CARPENTER_PROXMOX_TOKEN_SECRET",
    )):
        result["discovery.proxmox_inventory"] = "1.0.0"
    if os.getenv("CARPENTER_KUBERNETES_API_URL") and os.getenv("CARPENTER_KUBERNETES_TOKEN"):
        result["platform.kubernetes_deploy"] = "1.0.0"
        result["discovery.kubernetes_inventory"] = "1.0.0"
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
    iac_resource = payload.get("iac_resource")
    iac_fingerprint = str(payload.get("iac_fingerprint", ""))
    node = os.environ["CARPENTER_PROXMOX_NODE"]
    proxmox_url = urllib.parse.urlparse(os.environ["CARPENTER_PROXMOX_URL"])
    endpoint = (proxmox_url.hostname or "unknown-proxmox") + (f":{proxmox_url.port}" if proxmox_url.port else "")
    template_vmid = int(os.environ["CARPENTER_PROXMOX_TEMPLATE_VMID"])
    if not re.fullmatch(r"[a-f0-9-]{16,64}", deployment_id):
        raise ValueError("A valid Carpenter deployment ID is required")
    if not isinstance(vm_definitions, list) or len(vm_definitions) != 1:
        raise ValueError("A Proxmox worker job must contain exactly one VM definition")
    if not re.fullmatch(r"[a-f0-9]{64}", iac_fingerprint):
        raise ValueError("A valid compiled IaC fingerprint is required")
    if (
        not isinstance(iac_resource, dict)
        or iac_resource.get("provider") != "proxmox"
        or iac_resource.get("kind") != "virtual_machine"
        or not isinstance(iac_resource.get("spec"), dict)
    ):
        raise ValueError("A generated Proxmox virtual-machine IaC resource is required")
    if vm_definitions[0] != iac_resource["spec"]:
        raise ValueError("VM job payload does not match its generated IaC resource")
    if template_vmid <= 0:
        raise ValueError("CARPENTER_PROXMOX_TEMPLATE_VMID must be a prepared cloud-init template")

    # Stable names allow a retry to recover a VM created before the previous
    # worker attempt lost its lease or acknowledgement.
    existing = _proxmox_request("GET", "/cluster/resources?type=vm") or []
    results = []
    observed_resources = [{
        "provider": "proxmox",
        "resource_type": "hypervisor_node",
        "native_id": f"nodes/{endpoint}/{node}",
        "name": node,
        "status": "online",
        "properties": {"node": node},
    }]
    observed_relationships = [{
        "source_provider": "carpenter-agent",
        "source_native_id": str(payload.get("worker_id") or ""),
        "target_provider": "proxmox",
        "target_native_id": f"nodes/{endpoint}/{node}",
        "relation": "manages",
    }] if payload.get("worker_id") else []
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
        vm_config = _proxmox_request(
            "GET", f"/nodes/{encoded_node}/qemu/{vmid}/config"
        ) or {}
        current = _proxmox_request(
            "GET", f"/nodes/{encoded_node}/qemu/{vmid}/status/current"
        ) or {}
        actual_cores = int(vm_config.get("cores", cores))
        actual_memory = int(vm_config.get("memory", memory_mb))
        state = str(current.get("status") or "started")
        results.append({
            "name": name, "vmid": vmid, "action": action, "status": state,
            "vcpu": actual_cores, "memory_mb": actual_memory,
        })
        vm_native = f"qemu/{endpoint}/{vmid}"
        observed_resources.append({
            "provider": "proxmox", "resource_type": "virtual_machine",
            "native_id": vm_native, "name": name, "status": state,
            "properties": {
                "vmid": vmid, "node": node, "action": action,
                "vcpu": actual_cores, "memory_mb": actual_memory,
            },
        })
        observed_relationships.append({
            "source_provider": "proxmox", "source_native_id": f"nodes/{endpoint}/{node}",
            "target_provider": "proxmox", "target_native_id": vm_native,
            "relation": "hosts",
        })
        for key, raw in vm_config.items():
            if re.fullmatch(r"net\d+", str(key)) and isinstance(raw, str):
                options = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
                bridge = options.get("bridge")
                if bridge:
                    bridge_native = f"network/{endpoint}/{node}/{bridge}"
                    observed_resources.append({
                        "provider": "proxmox", "resource_type": "network",
                        "native_id": bridge_native, "name": bridge, "status": "observed",
                        "properties": {"node": node, "bridge": bridge, "role": "virtual_bridge"},
                    })
                    observed_relationships.append({
                        "source_provider": "proxmox", "source_native_id": vm_native,
                        "target_provider": "proxmox", "target_native_id": bridge_native,
                        "relation": "connected_to",
                    })
            elif re.fullmatch(r"(?:scsi|virtio|sata|ide)\d+", str(key)) and isinstance(raw, str):
                volume_ref = raw.split(",", 1)[0]
                if ":" in volume_ref:
                    pool, volume_name = volume_ref.split(":", 1)
                    volume_native = f"volume/{endpoint}/{node}/{volume_ref}"
                    observed_resources.append({
                        "provider": "proxmox", "resource_type": "storage_volume",
                        "native_id": volume_native, "name": volume_name, "status": "attached",
                        "properties": {"node": node, "device": key, "storage_pool": pool},
                    })
                    observed_relationships.append({
                        "source_provider": "proxmox", "source_native_id": vm_native,
                        "target_provider": "proxmox", "target_native_id": volume_native,
                        "relation": "uses_storage",
                    })

    return {
        "deployment_id": deployment_id,
        "iac_fingerprint": iac_fingerprint,
        "worker_id": payload.get("worker_id"),
        "node": node,
        "cluster_endpoint": endpoint,
        "managed_node": node,
        "created_or_reconciled": results,
        "observed_resources": observed_resources,
        "observed_relationships": observed_relationships,
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
    manifests = payload.get("manifests")
    fingerprint = str(payload.get("iac_fingerprint", ""))
    if not re.fullmatch(r"[a-f0-9-]{16,64}", deployment_id):
        raise ValueError("A valid Carpenter deployment ID is required")
    if not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("A valid compiled IaC fingerprint is required")
    if not isinstance(manifests, list) or len(manifests) != 2:
        raise ValueError("The IaC bundle must contain exactly one Deployment and one Service manifest")

    by_kind: dict[str, dict[str, Any]] = {}
    for manifest in manifests:
        if not isinstance(manifest, dict) or manifest.get("kind") not in ("Deployment", "Service"):
            raise ValueError("Only generated Kubernetes Deployment and Service manifests are accepted")
        if manifest["kind"] in by_kind:
            raise ValueError("Duplicate Kubernetes resource kind in generated IaC")
        by_kind[manifest["kind"]] = manifest

    if set(by_kind) != {"Deployment", "Service"}:
        raise ValueError("Both a Deployment and Service manifest are required")

    deployment = by_kind["Deployment"]
    service = by_kind["Service"]
    metadata = deployment.get("metadata", {})
    service_metadata = service.get("metadata", {})
    name = str(metadata.get("name", ""))
    namespace = str(metadata.get("namespace", ""))
    if not _dns_label(name) or not _dns_label(namespace):
        raise ValueError("Generated Kubernetes names must be lowercase DNS labels")
    if service_metadata.get("name") != name or service_metadata.get("namespace") != namespace:
        raise ValueError("Generated Service must target the same workload and namespace")
    if deployment.get("apiVersion") != "apps/v1" or service.get("apiVersion") != "v1":
        raise ValueError("Generated Kubernetes API versions are not supported")

    spec = deployment.get("spec", {})
    replicas = spec.get("replicas")
    selector = spec.get("selector", {}).get("matchLabels", {})
    pod = spec.get("template", {}).get("spec", {})
    containers = pod.get("containers", [])
    if not isinstance(replicas, int) or isinstance(replicas, bool) or not 1 <= replicas <= 100:
        raise ValueError("Generated replica count is out of range")
    if not isinstance(containers, list) or len(containers) != 1:
        raise ValueError("Generated workload must contain exactly one container")
    container = containers[0]
    image = str(container.get("image", ""))
    if not image or len(image) > 512 or any(char.isspace() or ord(char) < 32 for char in image):
        raise ValueError("Generated container image is invalid")
    if not isinstance(selector, dict) or not selector:
        raise ValueError("Generated Deployment selector is required")

    deployment_ports = container.get("ports", [])
    service_ports = service.get("spec", {}).get("ports", [])
    if len(deployment_ports) != 1 or len(service_ports) != 1:
        raise ValueError("Generated workload must expose exactly one application port")
    port = deployment_ports[0].get("containerPort")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Generated application port is invalid")
    if service_ports[0].get("targetPort") != port:
        raise ValueError("Generated Service targetPort does not match the container port")
    if service.get("spec", {}).get("selector") != selector:
        raise ValueError("Generated Service selector does not match the Deployment selector")

    encoded_namespace = urllib.parse.quote(namespace, safe="")
    deployment_result = _kubernetes_apply(
        f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments/{name}", deployment
    )
    service_result = _kubernetes_apply(
        f"/api/v1/namespaces/{encoded_namespace}/services/{name}", service
    )
    api = urllib.parse.urlparse(os.environ["CARPENTER_KUBERNETES_API_URL"])
    endpoint = (api.hostname or "unknown-cluster") + (f":{api.port}" if api.port else "")
    deployment_status = deployment_result.get("status", {}) if isinstance(deployment_result, dict) else {}
    service_spec = service_result.get("spec", {}) if isinstance(service_result, dict) else {}
    observed_resources = [
        {
            "provider": "kubernetes", "resource_type": "cluster",
            "native_id": f"api/{endpoint}", "name": endpoint, "status": "reachable",
            "properties": {"cluster_endpoint": endpoint},
        },
        {
            "provider": "kubernetes", "resource_type": "namespace",
            "native_id": f"namespace/{endpoint}/{namespace}", "name": namespace, "status": "observed",
            "properties": {"namespace": namespace},
        },
        {
            "provider": "kubernetes", "resource_type": "workload",
            "native_id": f"deployments/{endpoint}/{namespace}/{name}", "name": name,
            "status": "ready" if int(deployment_status.get("readyReplicas", 0) or 0) >= replicas else "applied",
            "properties": {
                "namespace": namespace, "image": image, "replicas": replicas,
                "ready_replicas": int(deployment_status.get("readyReplicas", 0) or 0),
                "selector": selector,
                "uid": (deployment_result.get("metadata", {}) or {}).get("uid"),
                "generation": (deployment_result.get("metadata", {}) or {}).get("generation"),
                "resource_version": (deployment_result.get("metadata", {}) or {}).get("resourceVersion"),
            },
        },
        {
            "provider": "kubernetes", "resource_type": "service",
            "native_id": f"services/{endpoint}/{namespace}/{name}", "name": name, "status": "applied",
            "properties": {
                "namespace": namespace, "service_type": service_spec.get("type", "ClusterIP"),
                "port": (service_spec.get("ports") or [{}])[0].get("port", port),
                "target_port": (service_spec.get("ports") or [{}])[0].get("targetPort", port),
                "protocol": (service_spec.get("ports") or [{}])[0].get("protocol", "TCP"),
                "cluster_ip": service_spec.get("clusterIP"),
            },
        },
    ]
    observed_relationships = [
        {"source_provider": "kubernetes", "source_native_id": f"api/{endpoint}",
         "target_provider": "kubernetes", "target_native_id": f"namespace/{endpoint}/{namespace}",
         "relation": "contains"},
        {"source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
         "target_provider": "kubernetes", "target_native_id": f"deployments/{endpoint}/{namespace}/{name}",
         "relation": "contains"},
        {"source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
         "target_provider": "kubernetes", "target_native_id": f"services/{endpoint}/{namespace}/{name}",
         "relation": "contains"},
        {"source_provider": "kubernetes", "source_native_id": f"services/{endpoint}/{namespace}/{name}",
         "target_provider": "kubernetes", "target_native_id": f"deployments/{endpoint}/{namespace}/{name}",
         "relation": "routes_to"},
    ]
    return {
        "deployment_id": deployment_id,
        "iac_fingerprint": fingerprint,
        "applied_resources": [
            {"kind": "Deployment", "name": name, "namespace": namespace},
            {"kind": "Service", "name": name, "namespace": namespace},
        ],
        "observed_resources": observed_resources,
        "observed_relationships": observed_relationships,
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
    if not isinstance(result, dict) or str(result.get("status", "")).lower() not in ("succeeded", "completed"):
        raise RuntimeError(
            "GAMGEE installer must return a terminal status of 'succeeded' or 'completed'; "
            "an accepted/queued response is not treated as a completed deployment."
        )
    return {"deployment_id": deployment_id, "installer_response": result, "execution_status": "succeeded"}


def proxmox_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    """Read the Proxmox cluster resource inventory and selected VM attachments."""
    proxmox_url = urllib.parse.urlparse(os.environ["CARPENTER_PROXMOX_URL"])
    endpoint = (proxmox_url.hostname or "unknown-proxmox") + (f":{proxmox_url.port}" if proxmox_url.port else "")
    rows = _proxmox_request("GET", "/cluster/resources") or []
    observed_resources: list[dict[str, Any]] = []
    observed_relationships: list[dict[str, Any]] = []
    nodes: set[str] = set()
    vm_configs: list[tuple[str, str, int]] = []

    def resource(provider: str, resource_type: str, native_id: str, name: str,
                 status: str, properties: dict[str, Any]) -> None:
        observed_resources.append({
            "provider": provider, "resource_type": resource_type,
            "native_id": native_id, "name": name, "status": status,
            "properties": properties,
        })

    for item in rows[:1000]:
        kind = str(item.get("type") or "")
        node = str(item.get("node") or "")
        if kind == "node" and node:
            nodes.add(node)
            resource("proxmox", "hypervisor_node", f"nodes/{endpoint}/{node}", node,
                     str(item.get("status") or "observed"), {
                         **{"node": node},
                         **{key: item.get(key) for key in ("cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime")
                            if item.get(key) is not None}
                     })
        elif kind in {"qemu", "lxc"} and node:
            nodes.add(node)
            vmid = str(item.get("vmid") or item.get("id", "").split("/")[-1])
            if not vmid:
                continue
            native = f"{kind}/{endpoint}/{vmid}"
            resource("proxmox", "virtual_machine", native,
                     str(item.get("name") or vmid), str(item.get("status") or "observed"), {
                         key: item.get(key) for key in ("vmid", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime")
                         if item.get(key) is not None
                     })
            observed_relationships.append({
                "source_provider": "proxmox", "source_native_id": f"nodes/{endpoint}/{node}",
                "target_provider": "proxmox", "target_native_id": native,
                "relation": "hosts",
            })
            if kind == "qemu" and len(vm_configs) < 100:
                vm_configs.append((node, vmid, 0))
        elif kind == "storage" and node:
            nodes.add(node)
            storage_name = str(item.get("storage") or (str(item.get("id", "")).split("/")[1] if len(str(item.get("id", "")).split("/")) > 1 else ""))
            if not storage_name:
                continue
            native = f"storage/{endpoint}/{node}/{storage_name}"
            resource("proxmox", "storage_pool", native, storage_name,
                     str(item.get("status") or "observed"), {
                         key: item.get(key) for key in ("type", "content", "used", "total", "shared")
                         if item.get(key) is not None
                     })
            observed_relationships.append({
                "source_provider": "proxmox", "source_native_id": f"nodes/{endpoint}/{node}",
                "target_provider": "proxmox", "target_native_id": native,
                "relation": "provides_storage",
            })

    for node in sorted(nodes):
        if not any(item.get("native_id") == f"nodes/{endpoint}/{node}" for item in observed_resources):
            resource("proxmox", "hypervisor_node", f"nodes/{endpoint}/{node}", node, "observed", {"node": node})

    # Read per-VM configuration to expose virtual bridges and storage attachments.
    for node, vmid, _ in vm_configs:
        encoded_node = urllib.parse.quote(node, safe="")
        try:
            config = _proxmox_request("GET", f"/nodes/{encoded_node}/qemu/{vmid}/config") or {}
        except Exception:
            continue
        vm_native = f"qemu/{endpoint}/{vmid}"
        for key, raw in config.items():
            if re.fullmatch(r"net\d+", str(key)) and isinstance(raw, str):
                options = dict(part.split("=", 1) for part in raw.split(",") if "=" in part)
                bridge = options.get("bridge")
                if bridge:
                    bridge_native = f"network/{endpoint}/{node}/{bridge}"
                    resource("proxmox", "network", bridge_native, bridge, "observed", {
                        "node": node, "bridge": bridge, "role": "virtual_bridge",
                    })
                    observed_relationships.append({
                        "source_provider": "proxmox", "source_native_id": vm_native,
                        "target_provider": "proxmox", "target_native_id": bridge_native,
                        "relation": "connected_to",
                    })
            elif re.fullmatch(r"(?:scsi|virtio|sata|ide)\d+", str(key)) and isinstance(raw, str):
                volume_ref = raw.split(",", 1)[0]
                if ":" in volume_ref:
                    pool, volume_name = volume_ref.split(":", 1)
                    volume_native = f"volume/{endpoint}/{node}/{volume_ref}"
                    resource("proxmox", "storage_volume", volume_native, volume_name, "attached", {
                        "node": node, "device": key, "storage_pool": pool,
                    })
                    observed_relationships.append({
                        "source_provider": "proxmox", "source_native_id": vm_native,
                        "target_provider": "proxmox", "target_native_id": volume_native,
                        "relation": "uses_storage",
                    })

    return {
        "provider": "proxmox",
        "cluster_endpoint": endpoint,
        "managed_node": os.getenv("CARPENTER_PROXMOX_NODE"),
        "observed_resources": observed_resources,
        "observed_relationships": observed_relationships,
        "inventory_complete": True,
        "resource_count": len(observed_resources),
    }


def _kubernetes_read(path: str) -> dict[str, Any]:
    api_url = os.environ["CARPENTER_KUBERNETES_API_URL"].rstrip("/")
    token = os.environ["CARPENTER_KUBERNETES_TOKEN"]
    if not api_url.startswith("https://"):
        raise ValueError("Kubernetes API URL must use HTTPS")
    request = urllib.request.Request(
        api_url + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, context=ssl.create_default_context(), timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Kubernetes inventory request failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Kubernetes inventory returned a non-object response")
    return payload


def kubernetes_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    """Observe namespaced Kubernetes objects visible to this worker's service account."""
    api = urllib.parse.urlparse(os.environ["CARPENTER_KUBERNETES_API_URL"])
    endpoint = (api.hostname or "unknown-cluster") + (f":{api.port}" if api.port else "")
    namespace = str(payload.get("namespace") or os.getenv("CARPENTER_KUBERNETES_NAMESPACE", "default"))
    if not _dns_label(namespace):
        raise ValueError("Kubernetes inventory namespace must be a lowercase DNS label")
    encoded_namespace = urllib.parse.quote(namespace, safe="")
    observed_resources: list[dict[str, Any]] = [
        {
            "provider": "kubernetes", "resource_type": "cluster",
            "native_id": f"api/{endpoint}", "name": endpoint,
            "status": "reachable", "properties": {"cluster_endpoint": endpoint},
        },
        {
            "provider": "kubernetes", "resource_type": "namespace",
            "native_id": f"namespace/{endpoint}/{namespace}", "name": namespace,
            "status": "observed", "properties": {"namespace": namespace},
        },
    ]
    observed_relationships: list[dict[str, Any]] = [{
        "source_provider": "kubernetes", "source_native_id": f"api/{endpoint}",
        "target_provider": "kubernetes", "target_native_id": f"namespace/{endpoint}/{namespace}",
        "relation": "contains",
    }]
    warnings: list[str] = []

    def list_items(path: str) -> list[dict[str, Any]]:
        try:
            result = _kubernetes_read(path)
            items = result.get("items", [])
            return items if isinstance(items, list) else []
        except Exception as exc:
            warnings.append(f"{path.rsplit('/', 1)[-1]}: {type(exc).__name__}")
            return []

    workloads: list[dict[str, Any]] = []
    for plural, api_path in (
        ("deployments", f"/apis/apps/v1/namespaces/{encoded_namespace}/deployments"),
        ("statefulsets", f"/apis/apps/v1/namespaces/{encoded_namespace}/statefulsets"),
        ("daemonsets", f"/apis/apps/v1/namespaces/{encoded_namespace}/daemonsets"),
        ("replicasets", f"/apis/apps/v1/namespaces/{encoded_namespace}/replicasets"),
    ):
        for item in list_items(api_path)[:300]:
            metadata = item.get("metadata") or {}
            spec = item.get("spec") or {}
            status = item.get("status") or {}
            name = str(metadata.get("name") or "")
            if not name:
                continue
            desired = int(spec.get("replicas", 1) or 1)
            ready = int(status.get("readyReplicas", status.get("numberReady", 0)) or 0)
            kind = plural.rstrip("s")
            native = f"{plural}/{endpoint}/{namespace}/{name}"
            containers = (
                ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
            )
            images = [str(container.get("image")) for container in containers if container.get("image")]
            selector = ((spec.get("selector") or {}).get("matchLabels") or {})
            resource_status = "ready" if desired > 0 and ready >= desired else "applied"
            observed_resources.append({
                "provider": "kubernetes", "resource_type": "workload",
                "native_id": native, "name": name, "status": resource_status,
                "properties": {
                    "namespace": namespace, "replicas": desired, "ready_replicas": ready,
                    "image": ", ".join(images[:6]), "selector": selector,
                    "uid": metadata.get("uid"), "generation": metadata.get("generation"),
                    "resource_version": metadata.get("resourceVersion"), "kind": plural,
                },
            })
            observed_relationships.append({
                "source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
                "target_provider": "kubernetes", "target_native_id": native,
                "relation": "contains",
            })
            owner_references = metadata.get("ownerReferences") or []
            workloads.append({
                "native_id": native, "selector": selector,
                "owner_references": owner_references,
            })
            for owner in owner_references:
                owner_name = str(owner.get("name") or "")
                owner_kind = str(owner.get("kind") or "").casefold()
                if not owner_name:
                    continue
                parent_plural = {
                    "deployment": "deployments",
                    "statefulset": "statefulsets",
                    "daemonset": "daemonsets",
                }.get(owner_kind)
                if parent_plural:
                    observed_relationships.append({
                        "source_provider": "kubernetes",
                        "source_native_id": native,
                        "target_provider": "kubernetes",
                        "target_native_id": f"{parent_plural}/{endpoint}/{namespace}/{owner_name}",
                        "relation": "managed_by",
                    })

    services = list_items(f"/api/v1/namespaces/{encoded_namespace}/services")
    for item in services[:300]:
        metadata = item.get("metadata") or {}
        spec = item.get("spec") or {}
        name = str(metadata.get("name") or "")
        if not name:
            continue
        native = f"services/{endpoint}/{namespace}/{name}"
        observed_resources.append({
            "provider": "kubernetes", "resource_type": "service",
            "native_id": native, "name": name, "status": "observed",
            "properties": {
                "namespace": namespace, "service_type": spec.get("type", "ClusterIP"),
                "cluster_ip": spec.get("clusterIP"),
                "port": (spec.get("ports") or [{}])[0].get("port"),
                "target_port": (spec.get("ports") or [{}])[0].get("targetPort"),
                "protocol": (spec.get("ports") or [{}])[0].get("protocol", "TCP"),
                "selector": spec.get("selector") or {},
            },
        })
        observed_relationships.append({
            "source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
            "target_provider": "kubernetes", "target_native_id": native,
            "relation": "contains",
        })
        cluster_ip = str(spec.get("clusterIP") or "")
        if cluster_ip and cluster_ip.casefold() != "none":
            try:
                address = ipaddress.ip_address(cluster_ip)
            except ValueError:
                address = None
            if address is not None:
                network_native = f"service-ip/{endpoint}/{cluster_ip}"
                observed_resources.append({
                    "provider": "kubernetes", "resource_type": "network",
                    "native_id": network_native, "name": cluster_ip, "status": "observed",
                    "properties": {"address": cluster_ip, "role": "service_cluster_ip"},
                })
                observed_relationships.append({
                    "source_provider": "kubernetes",
                    "source_native_id": native,
                    "target_provider": "kubernetes",
                    "target_native_id": network_native,
                    "relation": "exposes",
                })
        selector = spec.get("selector") or {}
        for workload in workloads:
            labels = workload.get("selector") or {}
            if selector and all(labels.get(key) == value for key, value in selector.items()):
                observed_relationships.append({
                    "source_provider": "kubernetes", "source_native_id": native,
                    "target_provider": "kubernetes", "target_native_id": workload["native_id"],
                    "relation": "routes_to",
                })

    claims: list[tuple[str, str]] = []
    for item in list_items(f"/api/v1/namespaces/{encoded_namespace}/persistentvolumeclaims")[:300]:
        metadata = item.get("metadata") or {}
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        name = str(metadata.get("name") or "")
        if not name:
            continue
        native = f"pvc/{endpoint}/{namespace}/{name}"
        observed_resources.append({
            "provider": "kubernetes", "resource_type": "storage_volume",
            "native_id": native, "name": name,
            "status": str(status.get("phase") or "Pending").casefold(),
            "properties": {
                "namespace": namespace, "phase": status.get("phase"),
                "storage_class": spec.get("storageClassName"),
                "storage_request": (spec.get("resources") or {}).get("requests", {}).get("storage"),
                "access_modes": spec.get("accessModes") or [],
            },
        })
        observed_relationships.append({
            "source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
            "target_provider": "kubernetes", "target_native_id": native,
            "relation": "contains",
        })
        volume_name = str(spec.get("volumeName") or "")
        if volume_name:
            claims.append((native, volume_name))

    if claims:
        for item in list_items("/api/v1/persistentvolumes")[:500]:
            metadata = item.get("metadata") or {}
            spec = item.get("spec") or {}
            status = item.get("status") or {}
            name = str(metadata.get("name") or "")
            if not name or not any(name == target for _, target in claims):
                continue
            native = f"persistentvolume/{endpoint}/{name}"
            observed_resources.append({
                "provider": "kubernetes", "resource_type": "storage_volume",
                "native_id": native, "name": name,
                "status": str(status.get("phase") or "observed").casefold(),
                "properties": {
                    "capacity": (spec.get("capacity") or {}).get("storage"),
                    "storage_class": spec.get("storageClassName"),
                    "access_modes": spec.get("accessModes") or [],
                    "reclaim_policy": spec.get("persistentVolumeReclaimPolicy"),
                },
            })
            for claim_id, target in claims:
                if target == name:
                    observed_relationships.append({
                        "source_provider": "kubernetes", "source_native_id": claim_id,
                        "target_provider": "kubernetes", "target_native_id": native,
                        "relation": "bound_to",
                    })

    for item in list_items(f"/api/v1/namespaces/{encoded_namespace}/pods")[:500]:
        metadata = item.get("metadata") or {}
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        name = str(metadata.get("name") or "")
        if not name:
            continue
        native = f"pods/{endpoint}/{namespace}/{name}"
        phase = str(status.get("phase") or "Unknown").casefold()
        observed_resources.append({
            "provider": "kubernetes", "resource_type": "workload_instance",
            "native_id": native, "name": name, "status": phase,
            "properties": {
                "namespace": namespace, "phase": status.get("phase"),
                "node_name": spec.get("nodeName"), "pod_ip": status.get("podIP"),
                "restart_count": sum(
                    int(container.get("restartCount", 0) or 0)
                    for container in (status.get("containerStatuses") or [])
                ),
            },
        })
        observed_relationships.append({
            "source_provider": "kubernetes", "source_native_id": f"namespace/{endpoint}/{namespace}",
            "target_provider": "kubernetes", "target_native_id": native,
            "relation": "contains",
        })
        owner = next(iter(metadata.get("ownerReferences") or []), {})
        owner_name = owner.get("name")
        if owner_name:
            for workload in workloads:
                if workload["native_id"].endswith("/" + owner_name):
                    observed_relationships.append({
                        "source_provider": "kubernetes", "source_native_id": native,
                        "target_provider": "kubernetes", "target_native_id": workload["native_id"],
                        "relation": "instance_of",
                    })
                    break
        node_name = str(spec.get("nodeName") or "")
        if node_name:
            node_native = f"nodes/{endpoint}/{node_name}"
            if not any(item.get("native_id") == node_native for item in observed_resources):
                observed_resources.append({
                    "provider": "kubernetes", "resource_type": "compute_host",
                    "native_id": node_native, "name": node_name, "status": "observed",
                    "properties": {"node_name": node_name, "role": "kubernetes_worker_node"},
                })
                observed_relationships.append({
                    "source_provider": "kubernetes", "source_native_id": f"api/{endpoint}",
                    "target_provider": "kubernetes", "target_native_id": node_native,
                    "relation": "contains",
                })
            observed_relationships.append({
                "source_provider": "kubernetes", "source_native_id": native,
                "target_provider": "kubernetes", "target_native_id": node_native,
                "relation": "scheduled_on",
            })

    if len(observed_resources) <= 2 and warnings:
        raise RuntimeError("Kubernetes inventory could not read any namespaced resources.")
    return {
        "provider": "kubernetes", "namespace": namespace,
        "observed_resources": observed_resources,
        "observed_relationships": observed_relationships,
        "inventory_complete": not warnings,
        "warnings": warnings[:20],
        "resource_count": len(observed_resources),
    }


HANDLERS = {
    "discovery.host_inventory": host_inventory,
    "discovery.hypervisor_probe": hypervisor_probe,
    "discovery.storage_network": storage_network,
    "discovery.proxmox_inventory": proxmox_inventory,
    "discovery.kubernetes_inventory": kubernetes_inventory,
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
