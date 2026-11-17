from __future__ import annotations

from app import store


FUNCTIONS = [
    ("discovery.host_inventory", "1.0.0", "Collect read-only host CPU, memory, OS and disk inventory."),
    ("discovery.hypervisor_probe", "1.0.0", "Detect local KVM, libvirt, Proxmox and container runtime capabilities."),
    ("discovery.storage_network", "1.0.0", "Inspect mounted storage, network interfaces and counters."),
    ("operations.metrics_snapshot", "1.0.0", "Collect a read-only CPU, memory, disk and network metrics snapshot."),
    ("network.tcp_probe", "1.0.0", "Probe explicitly supplied private IP addresses on allow-listed TCP ports."),
    ("compute.proxmox_deploy", "1.0.0", "Clone and start cloud-init template VMs on the configured local Proxmox node."),
    ("platform.kubernetes_deploy", "1.0.0", "Server-side apply a generated Kubernetes Deployment and ClusterIP Service."),
    ("gamgee.bootstrap", "1.0.0", "Send a signed bootstrap/expand request to the configured GAMGEE installer endpoint."),
]


def register_worker_functions() -> None:
    for name, version, description in FUNCTIONS:
        store.register_function(name, version, description, digest="carpenter-worker-builtin-v1")
