from __future__ import annotations

from typing import Any


GIB = 1024 ** 3


def plan_placement(
    hosts: list[dict[str, Any]],
    vm_count: int,
    vcpu_per_vm: int = 2,
    memory_gb_per_vm: int = 4,
    disk_gb_per_vm: int = 40,
    high_availability: bool = False,
    cpu_reserve_ratio: float = 0.15,
    memory_reserve_ratio: float = 0.20,
    disk_reserve_ratio: float = 0.15,
) -> dict[str, Any]:
    """Greedy best-fit placement with headroom and failure-domain spreading.

    This is a conservative first-pass scheduler. It does not model NUMA, IOPS,
    network bandwidth, GPU, ballooning, live workloads or storage topology.
    """
    if not 1 <= vm_count <= 10000:
        raise ValueError("vm_count must be between 1 and 10000")
    if min(vcpu_per_vm, memory_gb_per_vm, disk_gb_per_vm) <= 0:
        raise ValueError("VM resource sizes must be positive")
    if not hosts:
        return {"feasible": False, "placements": [], "unplaced": vm_count,
                "reasons": ["No online hosts are enrolled."]}

    pool: list[dict[str, Any]] = []
    for host in hosts:
        cpu = max(0, int(host.get("cpu_cores", 0)))
        mem_total = max(0, int(host.get("memory_total_bytes", 0)))
        mem_available = max(0, int(host.get("memory_available_bytes", 0)))
        disk_free = max(0, int(host.get("disk_free_bytes", 0)))
        caps = host.get("discovery", {})
        virt = caps.get("hypervisor", {}) if isinstance(caps, dict) else {}
        pool.append({
            "node_id": host.get("node_id", host.get("hostname", "unknown")),
            "hostname": host.get("hostname", "unknown"),
            "failure_domain": host.get("failure_domain", "default"),
            "cpu_free": int(cpu * (1.0 - cpu_reserve_ratio)),
            "memory_free_gb": min(mem_available, int(mem_total * (1.0 - memory_reserve_ratio))) / GIB,
            "disk_free_gb": disk_free / GIB * (1.0 - disk_reserve_ratio),
            "virtualization_available": bool(virt.get("kvm_device") or virt.get("libvirt_socket") or virt.get("proxmox_host")),
            "cpu_total": cpu,
        })

    placements: list[dict[str, Any]] = []
    spread_counts: dict[str, int] = {}
    for index in range(vm_count):
        candidates = [
            host for host in pool
            if host["cpu_free"] >= vcpu_per_vm
            and host["memory_free_gb"] >= memory_gb_per_vm
            and host["disk_free_gb"] >= disk_gb_per_vm
        ]
        if not candidates:
            break
        # For HA, prefer a previously unused failure domain; otherwise use best fit.
        candidates.sort(key=lambda host: (
            spread_counts.get(host["failure_domain"], 0) if high_availability else 0,
            (host["cpu_free"] - vcpu_per_vm)
            + (host["memory_free_gb"] - memory_gb_per_vm) * 2
            + (host["disk_free_gb"] - disk_gb_per_vm) * 0.1,
        ))
        selected = candidates[0]
        if high_availability and vm_count > 1 and not selected["virtualization_available"]:
            # A VM placement requires a verified hypervisor capability.
            virt_candidates = [h for h in candidates if h["virtualization_available"]]
            if virt_candidates:
                selected = virt_candidates[0]
        if not selected["virtualization_available"]:
            # Keep the plan honest: raw server capacity alone cannot create a VM.
            selected["cpu_free"] = 0
            selected["memory_free_gb"] = 0
            selected["disk_free_gb"] = 0
            continue

        selected["cpu_free"] -= vcpu_per_vm
        selected["memory_free_gb"] -= memory_gb_per_vm
        selected["disk_free_gb"] -= disk_gb_per_vm
        spread_counts[selected["failure_domain"]] = spread_counts.get(selected["failure_domain"], 0) + 1
        placements.append({
            "vm_name": f"carpenter-vm-{index + 1:03d}",
            "host_id": selected["node_id"],
            "hostname": selected["hostname"],
            "failure_domain": selected["failure_domain"],
            "vcpu": vcpu_per_vm,
            "memory_gb": memory_gb_per_vm,
            "disk_gb": disk_gb_per_vm,
        })

    unplaced = vm_count - len(placements)
    reasons = []
    if unplaced:
        reasons.append(f"{unplaced} VM(s) could not be placed with the current conservative headroom.")
    if high_availability:
        domains = {p["failure_domain"] for p in placements}
        if vm_count > 1 and len(domains) < 2:
            reasons.append("HA requested but placements do not span at least two failure domains.")
    return {
        "feasible": unplaced == 0 and (not high_availability or vm_count == 1 or len({p["failure_domain"] for p in placements}) >= 2),
        "requested_vm_count": vm_count,
        "placed_vm_count": len(placements),
        "unplaced": unplaced,
        "placements": placements,
        "failure_domains_used": sorted({p["failure_domain"] for p in placements}),
        "headroom": {
            "cpu_reserved_percent": round(cpu_reserve_ratio * 100),
            "memory_reserved_percent": round(memory_reserve_ratio * 100),
            "disk_reserved_percent": round(disk_reserve_ratio * 100),
        },
        "reasons": reasons,
        "execution_status": "plan_only",
    }


def forecast_capacity(samples: list[dict[str, float]], threshold_percent: float = 80.0) -> dict[str, Any]:
    """Simple linear least-squares forecast over timestamped utilisation samples."""
    clean = sorted(
        [(float(s["days_from_now"]), float(s["utilisation_percent"])) for s in samples],
        key=lambda item: item[0],
    )
    if len(clean) < 3:
        return {"forecast_available": False, "reason": "At least three time-series samples are required."}
    xs = [item[0] for item in clean]
    ys = [item[1] for item in clean]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return {"forecast_available": False, "reason": "Samples must span different times."}
    slope = sum((x - x_mean) * (y - y_mean) for x, y in clean) / denominator
    intercept = y_mean - slope * x_mean
    current = intercept
    if slope <= 0:
        days = None
    else:
        days = max(0.0, (threshold_percent - current) / slope)
    return {
        "forecast_available": True,
        "threshold_percent": threshold_percent,
        "current_estimated_percent": round(current, 2),
        "daily_growth_percent": round(slope, 4),
        "days_until_threshold": round(days, 1) if days is not None else None,
        "confidence": "basic-linear-trend; use as advisory only",
    }
