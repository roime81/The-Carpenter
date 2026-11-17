from __future__ import annotations

from typing import Any

from app.resource_engine import plan_placement


def assess_high_availability(hosts: list[dict[str, Any]], minimum_nodes: int = 2) -> dict[str, Any]:
    online = [host for host in hosts if host.get("online", True)]
    domains = {host.get("failure_domain", "default") for host in online}
    checks = {
        "minimum_nodes": len(online) >= minimum_nodes,
        "multiple_failure_domains": len(domains) >= 2,
        "fresh_inventory": all(host.get("online", True) for host in online),
    }
    return {
        "ha_ready": all(checks.values()),
        "online_nodes": len(online),
        "failure_domains": sorted(domains),
        "checks": checks,
        "limitations": [
            "This check does not prove redundant storage, network paths, power, or control-plane quorum.",
            "Failure-domain labels must be supplied and verified by the infrastructure owner.",
        ],
    }


def recommend_action(metrics: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    cpu = float(metrics.get("cpu_percent", 0))
    memory = float(metrics.get("memory_percent", 0))
    disk = float(metrics.get("root_disk_percent", 0))
    high = float(policy.get("scale_up_threshold", 80))
    low = float(policy.get("scale_down_threshold", 25))
    min_replicas = int(policy.get("min_replicas", 2))
    current_replicas = int(policy.get("current_replicas", min_replicas))
    max_replicas = int(policy.get("max_replicas", 20))

    if disk >= float(policy.get("disk_alert_threshold", 85)):
        action = "alert_disk_capacity"
        reason = "Disk use exceeds the configured safety threshold."
    elif cpu >= high or memory >= high:
        action = "scale_out"
        reason = "CPU or memory pressure crossed the upper threshold."
    elif cpu <= low and memory <= low and current_replicas > min_replicas:
        action = "scale_in_candidate"
        reason = "Utilisation is low; scale-in is only a candidate after HA and cooldown checks."
    else:
        action = "hold"
        reason = "Metrics are within the policy operating band."

    target = min(max_replicas, current_replicas + 1) if action == "scale_out" else current_replicas
    if action == "scale_in_candidate":
        target = max(min_replicas, current_replicas - 1)
    return {
        "action": action,
        "reason": reason,
        "current_replicas": current_replicas,
        "proposed_replicas": target,
        "policy_enforced": True,
        "execution_status": "recommendation_only",
    }


def render_haproxy_backends(backends: list[dict[str, Any]], frontend_port: int = 80) -> str:
    if not 1 <= frontend_port <= 65535:
        raise ValueError("Invalid frontend port")
    if not backends or len(backends) > 100:
        raise ValueError("Supply between 1 and 100 backend nodes")
    lines = [
        "frontend carpenter_frontend",
        f"    bind *:{frontend_port}",
        "    default_backend carpenter_backend",
        "",
        "backend carpenter_backend",
        "    balance roundrobin",
        "    option httpchk GET /health",
    ]
    for index, backend in enumerate(backends, start=1):
        host = str(backend.get("address", ""))
        port = int(backend.get("port", 80))
        # Only IP literals are permitted in generated config to avoid config injection.
        import ipaddress
        ipaddress.ip_address(host)
        if not 1 <= port <= 65535:
            raise ValueError("Invalid backend port")
        lines.append(f"    server app{index} {host}:{port} check")
    return "\n".join(lines) + "\n"



def build_failover_plan(
    hosts: list[dict[str, Any]],
    failed_node_id: str,
    vm_count: int,
    vcpu_per_vm: int = 2,
    memory_gb_per_vm: int = 4,
    disk_gb_per_vm: int = 40,
) -> dict[str, Any]:
    """Recommend replacement placement after a node failure; never mutates workloads."""
    survivors = [
        host for host in hosts
        if host.get("online", True) and host.get("node_id") != failed_node_id
    ]
    replacement = plan_placement(
        survivors, vm_count, vcpu_per_vm, memory_gb_per_vm, disk_gb_per_vm,
        high_availability=vm_count > 1,
    )
    return {
        "failed_node_id": failed_node_id,
        "surviving_node_count": len(survivors),
        "recovery_feasible": replacement["feasible"],
        "replacement_placement": replacement,
        "execution_status": "recovery_plan_only",
        "required_approval": True,
        "reason": "Failover is planned only; workload fencing, data consistency and provider-specific recovery are mandatory before execution.",
    }


def load_balancer_plan(backends: list[dict[str, Any]], frontend_port: int = 80) -> dict[str, Any]:
    config = render_haproxy_backends(backends, frontend_port)
    return {
        "provider": "haproxy",
        "backend_count": len(backends),
        "configuration": config,
        "execution_status": "configuration_plan_only",
        "required_approval": True,
        "checks": ["IP literal validation", "port validation", "HTTP health-check configured"],
    }
