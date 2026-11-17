from __future__ import annotations

from typing import Any

from app.runtime.faas import FunctionDefinition, FunctionRuntime


def assess_capacity(payload: dict[str, Any]) -> dict[str, Any]:
    hosts = payload.get("hosts", [])
    if not hosts:
        return {"host_count": 0, "total_cpu_cores": 0, "total_memory_gb": 0.0,
                "available_memory_gb": 0.0, "allocatable_memory_gb": 0.0}

    cpu = sum(int(host.get("cpu_cores", 0)) for host in hosts)
    memory_total = sum(int(host.get("memory_total_bytes", 0)) for host in hosts)
    memory_available = sum(int(host.get("memory_available_bytes", 0)) for host in hosts)
    gib = 1024 ** 3

    # Keep 20% headroom for the host OS, platform services and operational safety.
    allocatable = max(0, int(memory_total * 0.8))
    return {
        "host_count": len(hosts),
        "total_cpu_cores": cpu,
        "total_memory_gb": round(memory_total / gib, 2),
        "available_memory_gb": round(memory_available / gib, 2),
        "allocatable_memory_gb": round(allocatable / gib, 2),
        "headroom_policy": "20% reserved; preliminary estimate only",
    }


def build_deployment_plan(payload: dict[str, Any]) -> dict[str, Any]:
    capacity = payload["capacity"]
    vm_count = int(payload["vm_count"])
    vcpu_each = int(payload["vcpu_per_vm"])
    memory_each = int(payload["memory_gb_per_vm"])
    requested_memory = vm_count * memory_each
    requested_cpu = vm_count * vcpu_each
    allocatable_memory = float(capacity.get("allocatable_memory_gb", 0))
    total_cpu = int(capacity.get("total_cpu_cores", 0))

    memory_fits = requested_memory <= allocatable_memory
    # CPU oversubscription is not assumed in this first-pass estimate.
    cpu_fits = requested_cpu <= total_cpu
    return {
        "destination": payload["destination"],
        "service_model": payload["service_model"],
        "vm_count": vm_count,
        "vcpu_per_vm": vcpu_each,
        "memory_gb_per_vm": memory_each,
        "requested_vcpu": requested_cpu,
        "requested_memory_gb": requested_memory,
        "capacity_fit": memory_fits and cpu_fits,
        "checks": {
            "cpu_fit_without_oversubscription": cpu_fits,
            "memory_fit_with_20_percent_headroom": memory_fits,
        },
        "execution_status": "plan_only",
        "notice": "No VM, network, storage, or cloud resource has been created.",
    }


def recommend_scaling(payload: dict[str, Any]) -> dict[str, Any]:
    cpu = float(payload.get("cpu_percent", 0))
    memory = float(payload.get("memory_percent", 0))
    low = float(payload.get("scale_down_threshold", 30))
    high = float(payload.get("scale_up_threshold", 75))
    if cpu >= high or memory >= high:
        recommendation = "scale_up"
        reason = "CPU or memory pressure crossed the configured upper threshold."
    elif cpu <= low and memory <= low:
        recommendation = "scale_down_candidate"
        reason = "Both CPU and memory are below the lower threshold; verify HA and minimum capacity."
    else:
        recommendation = "hold"
        reason = "Utilisation is within the configured operating band."
    return {"recommendation": recommendation, "reason": reason,
            "cpu_percent": cpu, "memory_percent": memory}


def register_builtin_functions(runtime: FunctionRuntime) -> None:
    runtime.register(FunctionDefinition(
        name="assessment.capacity",
        handler=assess_capacity,
        description="Calculate preliminary aggregate compute and memory capacity from enrolled nodes.",
        timeout_seconds=5,
    ))
    runtime.register(FunctionDefinition(
        name="planning.deployment",
        handler=build_deployment_plan,
        description="Create a non-executing IaaS/PaaS deployment capacity plan.",
        timeout_seconds=5,
    ))
    runtime.register(FunctionDefinition(
        name="operations.scaling_recommendation",
        handler=recommend_scaling,
        description="Recommend scale-up, scale-down review, or hold from telemetry thresholds.",
        timeout_seconds=3,
    ))
