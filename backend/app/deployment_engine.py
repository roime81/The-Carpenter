from __future__ import annotations

from typing import Any

from app import store
from app.operations_engine import assess_high_availability
from app.resource_engine import plan_placement


class DeploymentEngine:
    """Plans cloud layouts and dispatches approved mutations as distributed FaaS jobs."""

    @staticmethod
    def _workers(hosts: list[dict[str, Any]], function_name: str) -> list[dict[str, Any]]:
        return [
            host for host in hosts
            if host.get("online", True)
            and host.get("capabilities", {}).get(function_name) == "1.0.0"
        ]

    def build_plan(self, request: dict[str, Any], hosts: list[dict[str, Any]]) -> dict[str, Any]:
        destination = request["destination"]
        model = request["service_model"]
        needs_vms = destination == "gamgee" or model in ("iaas", "hybrid")

        gamgee_workers = self._workers(hosts, "gamgee.bootstrap")
        proxmox_workers = [
            host for host in self._workers(hosts, "compute.proxmox_deploy")
            if host.get("discovery", {}).get("hypervisor", {}).get("proxmox_host")
        ]
        kubernetes_workers = self._workers(hosts, "platform.kubernetes_deploy")

        placement_hosts: list[dict[str, Any]] = hosts
        if destination == "own_cloud" and model in ("iaas", "hybrid"):
            placement_hosts = proxmox_workers

        placement = None
        if needs_vms:
            placement = plan_placement(
                placement_hosts,
                vm_count=request["vm_count"],
                vcpu_per_vm=request["vcpu_per_vm"],
                memory_gb_per_vm=request["memory_gb_per_vm"],
                disk_gb_per_vm=request["disk_gb_per_vm"],
                high_availability=request["high_availability"],
            )

        ha_assessments: dict[str, Any] = {}
        if request.get("high_availability"):
            if destination == "gamgee":
                ha_assessments["gamgee_data_plane"] = assess_high_availability(hosts)
            else:
                if model in ("iaas", "hybrid"):
                    ha_assessments["proxmox_execution_workers"] = assess_high_availability(proxmox_workers)
                if model in ("paas", "hybrid"):
                    ha_assessments["kubernetes_execution_workers"] = assess_high_availability(kubernetes_workers)

        adapter_checks = {
            "gamgee_worker_available": bool(gamgee_workers),
            "proxmox_worker_available": bool(proxmox_workers),
            "kubernetes_worker_available": bool(kubernetes_workers),
        }
        execution_workers = {
            "gamgee": [item["node_id"] for item in gamgee_workers],
            "proxmox": [item["node_id"] for item in proxmox_workers],
            "kubernetes": [item["node_id"] for item in kubernetes_workers],
        }

        if destination == "gamgee":
            adapter_ready = adapter_checks["gamgee_worker_available"]
        else:
            requirements = []
            if model in ("iaas", "hybrid"):
                requirements.append(adapter_checks["proxmox_worker_available"])
            if model in ("paas", "hybrid"):
                requirements.append(
                    adapter_checks["kubernetes_worker_available"]
                    and bool(request.get("container_image"))
                )
            adapter_ready = all(requirements)

        capacity_ready = bool(hosts) and (placement is None or bool(placement["feasible"]))
        ha_ready = all(item["ha_ready"] for item in ha_assessments.values()) if ha_assessments else True
        return {
            "destination": destination,
            "service_model": model,
            "requested": request,
            "host_count": len(hosts),
            "placement": placement,
            "ha_assessments": ha_assessments,
            "adapter_checks": adapter_checks,
            "execution_workers": execution_workers,
            "capacity_ready": capacity_ready,
            "ha_ready": ha_ready,
            "adapter_ready": adapter_ready,
            "ready_to_execute_after_approval": capacity_ready and ha_ready and adapter_ready,
            "execution_status": "plan_only",
            "limitations": [
                "No infrastructure changes are made while creating this plan.",
                "Provider mutations run as versioned Python FaaS jobs on selected data-plane workers.",
                "Proxmox placement uses only online workers advertising the configured Proxmox deployment function.",
                "PaaS requires an existing Kubernetes API; the worker must have a namespace-scoped service account.",
                "GAMGEE bootstrap requires a compatible signed installer endpoint configured on a worker.",
                "Hybrid deployments can partially succeed; cross-provider compensation is not yet implemented.",
            ],
        }

    def execute(self, deployment_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        """Queue approved provider operations. Does not perform provider API calls in the control plane."""
        if not plan.get("ready_to_execute_after_approval"):
            raise RuntimeError("Deployment plan is not ready: capacity, HA, or worker adapter checks failed.")

        destination = plan["destination"]
        model = plan["service_model"]
        request = plan["requested"]
        targets = plan["execution_workers"]
        queued_jobs: list[dict[str, Any]] = []

        if destination == "gamgee":
            worker_ids = targets["gamgee"]
            if not worker_ids:
                raise RuntimeError("No online worker advertises gamgee.bootstrap@1.0.0")
            payload = {
                "deployment_id": deployment_id,
                "action": "bootstrap-or-expand",
                "service_model": model,
                "requested": request,
                "placement": plan.get("placement"),
                "hosts": plan.get("host_count"),
                "target_nodes": [
                    item["host_id"] for item in (plan.get("placement") or {}).get("placements", [])
                ],
            }
            queued_jobs.append({
                "component": "gamgee",
                **store.enqueue_job(
                    "gamgee.bootstrap", "1.0.0", payload, max_attempts=3, priority=10,
                    idempotency_key=f"{deployment_id}:gamgee",
                    target_worker_id=worker_ids[0],
                ),
            })
        else:
            if model in ("iaas", "hybrid"):
                for index, placement in enumerate((plan.get("placement") or {}).get("placements", []), start=1):
                    worker_id = placement["host_id"]
                    vm_name = f"{request['name']}-{index:03d}"
                    vm_definition = {
                        "name": vm_name,
                        "vcpu": placement["vcpu"],
                        "memory_gb": placement["memory_gb"],
                        "disk_gb": placement["disk_gb"],
                    }
                    queued_jobs.append({
                        "component": f"proxmox:{worker_id}:{vm_name}",
                        **store.enqueue_job(
                            "compute.proxmox_deploy", "1.0.0",
                            {"deployment_id": deployment_id, "vms": [vm_definition]},
                            max_attempts=3, priority=10,
                            idempotency_key=f"{deployment_id}:proxmox:{worker_id}:{vm_name}",
                            target_worker_id=worker_id,
                        ),
                    })

            if model in ("paas", "hybrid"):
                worker_ids = targets["kubernetes"]
                if not worker_ids:
                    raise RuntimeError("No online worker advertises platform.kubernetes_deploy@1.0.0")
                queued_jobs.append({
                    "component": "kubernetes",
                    **store.enqueue_job(
                        "platform.kubernetes_deploy", "1.0.0",
                        {
                            "deployment_id": deployment_id,
                            "name": request["name"],
                            "namespace": request["namespace"],
                            "container_image": request["container_image"],
                            "replicas": request["vm_count"],
                            "container_port": request["container_port"],
                        },
                        max_attempts=3, priority=10,
                        idempotency_key=f"{deployment_id}:kubernetes",
                        target_worker_id=worker_ids[0],
                    ),
                })

        if not queued_jobs:
            raise RuntimeError("No provider execution jobs were generated for this deployment.")
        return {
            "deployment_id": deployment_id,
            "execution_status": "queued",
            "queued_jobs": queued_jobs,
            "delivery_semantics": "at-least-once; worker functions must remain idempotent",
        }
