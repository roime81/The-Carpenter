from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Any

from app import store

ALLOWED_TYPES = {
    "control_plane", "compute_host", "hypervisor_node", "hypervisor",
    "virtual_machine", "cluster", "namespace", "workload", "workload_instance", "service",
    "network", "network_interface", "storage_volume", "storage_pool", "container_runtime",
    "endpoint",
}
SAFE_PROPERTY_KEYS = {
    "hostname", "operating_system", "architecture", "cpu_cores", "cpu_percent",
    "memory_total_bytes", "memory_available_bytes", "disk_total_bytes", "disk_free_bytes",
    "ipv4_addresses", "failure_domain", "capabilities", "online", "last_seen",
    "kvm_device", "libvirt_socket", "libvirt_cli", "proxmox_host",
    "container_runtimes", "kubernetes_tools", "device", "mountpoint", "filesystem",
    "total_bytes", "free_bytes", "is_up", "speed_mbps", "addresses", "family",
    "address", "netmask", "network", "prefixlen", "interface", "bridge",
    "vmid", "action", "state", "status", "vcpu", "cores", "memory_mb",
    "memory_bytes", "disk_bytes", "native_id", "resource_version", "uid",
    "generation", "namespace", "image", "replicas", "ready_replicas", "selector",
    "service_type", "port", "target_port", "protocol", "cluster_endpoint", "cluster_ip", "api_server",
    "phase", "node_name", "pod_ip", "restart_count", "storage_class", "storage_request",
    "access_modes", "cpu", "maxcpu", "mem", "maxmem", "disk", "maxdisk", "uptime",
    "node", "provider", "name", "role", "version", "observed_at",
}


def resource_id(provider: str, native_id: str) -> str:
    identity = f"{provider.casefold().strip()}\0{native_id.strip()}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:28]
    return "twin:" + digest


CONTROL_PLANE_ID = resource_id("carpenter", "control-plane")


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return re.sub(r"(?i)(token|password|secret|credential|private[_-]?key)(\s*[:=]\s*)[^\s,;]+", r"\1\2[redacted]", value)[:500]
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        clean = {}
        for key, item in list(value.items())[:80]:
            name = str(key)
            lowered = name.casefold()
            if any(word in lowered for word in ("token", "password", "secret", "credential", "private_key", "authorization")):
                continue
            if name in SAFE_PROPERTY_KEYS or lowered in SAFE_PROPERTY_KEYS:
                clean[name] = _safe_value(item, depth + 1)
        return clean
    return str(value)[:160]


def _upsert(
    provider: str,
    native_id: str,
    resource_type: str,
    name: str,
    status: str,
    source: str,
    properties: dict[str, Any] | None = None,
    worker_id: str | None = None,
    deployment_id: str | None = None,
) -> str:
    if resource_type not in ALLOWED_TYPES:
        raise ValueError(f"Unsupported infrastructure resource type: {resource_type}")
    stable_id = resource_id(provider, native_id)
    store.upsert_twin_resource({
        "resource_id": stable_id,
        "resource_type": resource_type,
        "provider": provider[:80],
        "native_id": native_id[:300],
        "name": name[:200],
        "status": status[:48],
        "source": source[:100],
        "worker_id": worker_id,
        "deployment_id": deployment_id,
        "properties": _safe_value(properties or {}),
    })
    return stable_id


def _link(source_id: str, target_id: str, relation: str, source: str, metadata: dict[str, Any] | None = None) -> None:
    store.upsert_twin_relationship(source_id, target_id, relation, source, _safe_value(metadata or {}))


def _is_private_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


def ensure_control_plane() -> str:
    return _upsert(
        "carpenter", "control-plane", "control_plane", "The Carpenter Control Plane",
        "online", "control_plane",
        {"role": "orchestration", "product": "The Carpenter"},
    )


def observe_worker_heartbeat(inventory: dict[str, Any]) -> str:
    node_id = str(inventory.get("node_id") or "")
    if not node_id:
        raise ValueError("Worker heartbeat is missing node_id.")
    control_id = ensure_control_plane()
    props = {
        key: inventory.get(key) for key in (
            "hostname", "operating_system", "architecture", "cpu_cores",
            "memory_total_bytes", "disk_total_bytes", "ipv4_addresses", "failure_domain",
        ) if inventory.get(key) is not None
    }
    props["ipv4_addresses"] = [address for address in (inventory.get("ipv4_addresses") or []) if _is_private_address(str(address))][:24]
    props["capabilities"] = sorted((inventory.get("capabilities") or {}).keys())[:50]
    props["online"] = True
    host_id = _upsert(
        "carpenter-agent", node_id, "compute_host",
        str(inventory.get("hostname") or node_id), "online",
        "agent_heartbeat", props, worker_id=node_id,
    )
    _link(control_id, host_id, "manages", "agent_heartbeat")
    discovery = inventory.get("discovery") or {}
    _observe_hypervisor(node_id, host_id, discovery.get("hypervisor") or {})
    _observe_storage_network(node_id, host_id, discovery.get("storage_network") or {})
    return host_id


def _observe_hypervisor(worker_id: str, host_id: str, result: dict[str, Any]) -> None:
    if not result:
        return
    if result.get("proxmox_host") or result.get("kvm_device") or result.get("libvirt_socket"):
        label = "Proxmox VE" if result.get("proxmox_host") else "KVM / libvirt"
        hypervisor_id = _upsert(
            "linux-hypervisor", worker_id, "hypervisor",
            label + " on " + worker_id[:32], "observed",
            "hypervisor_probe",
            {key: result.get(key) for key in ("proxmox_host", "kvm_device", "libvirt_socket", "libvirt_cli") if key in result},
            worker_id=worker_id,
        )
        _link(host_id, hypervisor_id, "runs_hypervisor", "hypervisor_probe")
    for runtime, present in (result.get("container_runtimes") or {}).items():
        if present:
            runtime_id = _upsert(
                "container-runtime", f"{worker_id}/{runtime}", "container_runtime",
                runtime, "available", "hypervisor_probe",
                {"version": "unknown", "role": "runtime"}, worker_id=worker_id,
            )
            _link(host_id, runtime_id, "provides_runtime", "hypervisor_probe")


def _observe_storage_network(worker_id: str, host_id: str, result: dict[str, Any]) -> None:
    if not result:
        return
    for item in result.get("partitions", [])[:100]:
        device = str(item.get("device") or item.get("mountpoint") or "")
        if not device:
            continue
        native = f"{worker_id}/{device}"
        volume_id = _upsert(
            "linux-storage", native, "storage_volume",
            str(item.get("mountpoint") or device), "mounted",
            "storage_network",
            {key: item.get(key) for key in ("device", "mountpoint", "filesystem", "total_bytes", "free_bytes") if key in item},
            worker_id=worker_id,
        )
        _link(host_id, volume_id, "has_storage", "storage_network")
    for name, item in list((result.get("interfaces") or {}).items())[:100]:
        native = f"{worker_id}/{name}"
        addresses = [
            {"family": address.get("family"), "address": address.get("address"), "netmask": address.get("netmask")}
            for address in item.get("addresses", [])
            if _is_private_address(str(address.get("address", "")))
        ]
        interface_id = _upsert(
            "linux-network", native, "network_interface",
            str(name), "up" if item.get("is_up") else "down",
            "storage_network",
            {"is_up": bool(item.get("is_up")), "speed_mbps": item.get("speed_mbps"), "addresses": addresses},
            worker_id=worker_id,
        )
        _link(host_id, interface_id, "has_interface", "storage_network")
        for address in addresses:
            try:
                interface = ipaddress.ip_interface(f"{address['address']}/{address['netmask']}")
            except (ValueError, TypeError):
                continue
            network = interface.network
            if not (network.network_address.is_private or network.network_address.is_loopback or network.network_address.is_link_local):
                continue
            network_id = _upsert(
                "linux-network", f"{worker_id}/{network.with_prefixlen}", "network",
                network.with_prefixlen, "observed", "storage_network",
                {"network": network.with_prefixlen, "prefixlen": network.prefixlen},
                worker_id=worker_id,
            )
            _link(interface_id, network_id, "connected_to", "storage_network")


def observe_discovery_result(
    worker_id: str, function_name: str, result: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> None:
    inventory = store.get_agent(worker_id) or {"node_id": worker_id, "hostname": worker_id}
    observe_worker_heartbeat(inventory)
    if result.get("observed_resources"):
        scope = (job or {}).get("payload", {})
        _observe_canonical_resources({
            "function_name": function_name,
            "worker_id": worker_id,
            "payload": {"session_id": scope.get("session_id")},
        }, result, function_name)


def _observe_canonical_resources(
    job: dict[str, Any], result: dict[str, Any], source: str,
) -> list[str]:
    deployment_id = str((job.get("payload") or {}).get("deployment_id") or result.get("deployment_id") or "")
    worker_id = str(job.get("worker_id") or job.get("target_worker_id") or "")
    created: dict[tuple[str, str], str] = {}
    resources = result.get("observed_resources") or []
    if not isinstance(resources, list):
        return []
    for item in resources[:200]:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "")
        native_id = str(item.get("native_id") or "")
        resource_type = str(item.get("resource_type") or "")
        if not provider or not native_id or resource_type not in ALLOWED_TYPES:
            continue
        rid = _upsert(
            provider, native_id, resource_type,
            str(item.get("name") or native_id), str(item.get("status") or "observed"),
            source, item.get("properties") if isinstance(item.get("properties"), dict) else {},
            worker_id=worker_id or None, deployment_id=deployment_id or None,
        )
        created[(provider, native_id)] = rid
        if provider == "proxmox" and resource_type == "hypervisor_node" and worker_id:
            agent_id = resource_id("carpenter-agent", worker_id)
            if store.get_twin_resource(agent_id):
                _link(agent_id, rid, "manages", source)
    for relation in (result.get("observed_relationships") or [])[:500]:
        if not isinstance(relation, dict):
            continue
        source_key = (str(relation.get("source_provider") or ""), str(relation.get("source_native_id") or ""))
        target_key = (str(relation.get("target_provider") or ""), str(relation.get("target_native_id") or ""))
        source_id = created.get(source_key) or resource_id(*source_key) if all(source_key) else ""
        target_id = created.get(target_key) or resource_id(*target_key) if all(target_key) else ""
        if source_id and target_id and store.get_twin_resource(source_id) and store.get_twin_resource(target_id):
            _link(source_id, target_id, str(relation.get("relation") or "related_to"), source, relation.get("metadata") or {})
    return list(created.values())


def observe_provider_result(job: dict[str, Any], result: dict[str, Any]) -> None:
    function_name = str(job.get("function_name") or "")
    if function_name.startswith("discovery."):
        observe_discovery_result(str(job.get("worker_id") or ""), function_name, result)
        return
    created = _observe_canonical_resources(job, result, "provider_apply")
    if created:
        return
    deployment_id = str((job.get("payload") or {}).get("deployment_id") or result.get("deployment_id") or "")
    worker_id = str(job.get("worker_id") or job.get("target_worker_id") or "")

    # Backward-compatible Proxmox result projection. New workers emit the
    # canonical observed_resources contract; older agents return these fields.
    if function_name == "compute.proxmox_deploy":
        node_name = str(result.get("node") or "unknown-proxmox-node")
        node_id = _upsert(
            "proxmox", f"nodes/{node_name}", "hypervisor_node", node_name,
            "online", "proxmox_worker_result",
            {"node": node_name}, worker_id=worker_id or None,
            deployment_id=deployment_id or None,
        )
        host_id = ensure_control_plane()
        if worker_id:
            agent_id = resource_id("carpenter-agent", worker_id)
            if store.get_twin_resource(agent_id):
                _link(agent_id, node_id, "manages", "proxmox_worker_result")
        spec = ((job.get("payload") or {}).get("iac_resource") or {}).get("spec") or {}
        for item in result.get("created_or_reconciled", [])[:100]:
            vmid = str(item.get("vmid") or "")
            if not vmid:
                continue
            vm_id = _upsert(
                "proxmox", f"qemu/{vmid}", "virtual_machine",
                str(item.get("name") or spec.get("name") or vmid),
                str(item.get("status") or "started"),
                "proxmox_worker_result",
                {"vmid": vmid, "action": item.get("action"), "vcpu": spec.get("vcpu"),
                 "memory_mb": int(spec.get("memory_gb") or 0) * 1024,
                 "deployment_id": deployment_id, "iac_fingerprint": result.get("iac_fingerprint")},
                worker_id=worker_id or None, deployment_id=deployment_id or None,
            )
            _link(node_id, vm_id, "hosts", "proxmox_worker_result")
            if worker_id:
                agent_id = resource_id("carpenter-agent", worker_id)
                if store.get_twin_resource(agent_id):
                    _link(agent_id, vm_id, "provisioned", "proxmox_worker_result")
        return

    if function_name == "gamgee.bootstrap":
        installer = result.get("installer_response") or {}
        # Only import inventory that the signed installer explicitly reports
        # using the same observed-resource schema as Carpenter-native workers.
        proxy_job = dict(job)
        observe = dict(installer) if isinstance(installer, dict) else {}
        observe["deployment_id"] = deployment_id
        _observe_canonical_resources(proxy_job, observe, "gamgee_installer_observation")


def list_twin_snapshot(limit: int = 500) -> dict[str, Any]:
    resources = store.list_twin_resources(limit)
    resource_ids = {item["resource_id"] for item in resources}
    relationships = [
        item for item in store.list_twin_relationships(limit * 4)
        if item["source_resource_id"] in resource_ids and item["target_resource_id"] in resource_ids
    ]
    agents = {item["node_id"]: item for item in store.list_agents(online_only=False)}
    for resource in resources:
        if resource["resource_type"] == "compute_host" and resource.get("provider") == "carpenter-agent" and resource.get("worker_id"):
            agent = agents.get(resource["worker_id"])
            resource["status"] = "online" if agent and agent.get("online") else "offline"
            if agent:
                resource["last_seen"] = agent.get("last_seen", resource.get("last_seen"))
                resource["properties"]["online"] = bool(agent.get("online"))
    return {"resources": resources, "relationships": relationships, "resource_count": len(resources),
            "relationship_count": len(relationships), "updated_at": max((item.get("updated_at", "") for item in resources), default="")}
