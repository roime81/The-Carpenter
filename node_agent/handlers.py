from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import time
from pathlib import Path
from typing import Any

import psutil


FUNCTION_VERSIONS = {
    "discovery.host_inventory": "1.0.0",
    "discovery.hypervisor_probe": "1.0.0",
    "discovery.storage_network": "1.0.0",
    "operations.metrics_snapshot": "1.0.0",
    "network.tcp_probe": "1.0.0",
}
SAFE_TCP_PORTS = {22, 80, 443, 6443, 8006, 8080, 8443, 9090, 9100, 9443}


def _inventory() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "operating_system": __import__("platform").platform(),
        "architecture": __import__("platform").machine(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "cpu_percent": psutil.cpu_percent(interval=0.2),
        "memory_total_bytes": psutil.virtual_memory().total,
        "memory_available_bytes": psutil.virtual_memory().available,
        "disk_total_bytes": psutil.disk_usage(os.path.abspath(os.sep)).total,
        "disk_free_bytes": psutil.disk_usage("/").free,
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
    disk = psutil.disk_usage("/")
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


HANDLERS = {
    "discovery.host_inventory": host_inventory,
    "discovery.hypervisor_probe": hypervisor_probe,
    "discovery.storage_network": storage_network,
    "operations.metrics_snapshot": metrics_snapshot,
    "network.tcp_probe": tcp_probe,
}


def execute(function_name: str, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    expected = FUNCTION_VERSIONS.get(function_name)
    handler = HANDLERS.get(function_name)
    if handler is None or expected != version:
        raise ValueError(f"Function is not installed on this worker: {function_name}@{version}")
    result = handler(payload)
    if not isinstance(result, dict):
        raise TypeError("Worker functions must return JSON object results")
    return result
