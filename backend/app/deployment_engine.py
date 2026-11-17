from __future__ import annotations

from typing import Any

from app.adapters.gamgee import GamgeeInstallerAdapter
from app.adapters.kubernetes import KubernetesAdapter
from app.adapters.proxmox import ProxmoxAdapter
from app.config import settings
from app.operations_engine import assess_high_availability
from app.resource_engine import plan_placement


class DeploymentEngine:
    """Plans both cloud paths and invokes only explicitly configured adapters."""

    def build_plan(self, request: dict[str, Any], hosts: list[dict[str, Any]]) -> dict[str, Any]:
        destination = request["destination"]
        model = request["service_model"]
        needs_vms = destination == "gamgee" or model in ("iaas", "hybrid")
        ha = assess_high_availability(hosts) if request.get("high_availability") else None
        placement_hosts = hosts
        if destination == "own_cloud" and model in ("iaas", "hybrid"):
            # The current IaaS execution adapter is Proxmox only. Do not allocate
            # onto a generic KVM host that the configured Proxmox API cannot manage.
            placement_hosts = [
                host for host in hosts
                if host.get("discovery", {}).get("hypervisor", {}).get("proxmox_host")
                and settings.proxmox_node in (host.get("hostname"), host.get("node_id"))
            ]
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

        adapter_checks = {
            "gamgee_installer_configured": bool(settings.gamgee_installer_url and settings.gamgee_installer_token),
            "proxmox_configured": bool(
                settings.proxmox_url and settings.proxmox_token_id
                and settings.proxmox_token_secret and settings.proxmox_node
                and settings.proxmox_template_vmid > 0
            ),
            "kubernetes_configured": bool(settings.kubernetes_api_url and settings.kubernetes_token),
        }
        if destination == "gamgee":
            adapter_ready = adapter_checks["gamgee_installer_configured"]
        else:
            requirements = []
            if model in ("iaas", "hybrid"):
                requirements.append(adapter_checks["proxmox_configured"])
            if model in ("paas", "hybrid"):
                requirements.append(adapter_checks["kubernetes_configured"] and bool(request.get("container_image")))
            adapter_ready = all(requirements)

        capacity_ready = placement is None or bool(placement["feasible"])
        ha_ready = ha is None or bool(ha["ha_ready"])
        return {
            "destination": destination,
            "service_model": model,
            "requested": request,
            "host_count": len(hosts),
            "placement": placement,
            "ha_assessment": ha,
            "adapter_checks": adapter_checks,
            "capacity_ready": capacity_ready,
            "ha_ready": ha_ready,
            "adapter_ready": adapter_ready,
            "ready_to_execute_after_approval": capacity_ready and ha_ready and adapter_ready,
            "execution_status": "plan_only",
            "limitations": [
                "No infrastructure changes are made while creating this plan.",
                "VM placement is conservative and only uses hosts advertising a detected hypervisor.",
                "PaaS execution requires a pre-existing, reachable Kubernetes API and namespace permissions.",
                "GAMGEE bootstrap requires a compatible signed installer endpoint supplied by the GAMGEE project.",
            ],
        }

    def execute(self, deployment_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        if not plan.get("ready_to_execute_after_approval"):
            raise RuntimeError("Deployment plan is not ready: capacity, HA, or adapter checks failed.")

        destination = plan["destination"]
        model = plan["service_model"]
        request = plan["requested"]

        if destination == "gamgee":
            adapter = GamgeeInstallerAdapter(
                settings.gamgee_installer_url, settings.gamgee_installer_token
            )
            response = adapter.submit_bootstrap({
                "deployment_id": deployment_id,
                "action": "bootstrap-or-expand",
                "service_model": model,
                "requested": request,
                "placement": plan.get("placement"),
                "hosts": plan.get("host_count"),
            })
            return {"destination": "gamgee", "installer_response": response}

        results: dict[str, Any] = {"destination": "own_cloud", "components": {}}
        if model in ("iaas", "hybrid"):
            adapter = ProxmoxAdapter(
                settings.proxmox_url, settings.proxmox_token_id,
                settings.proxmox_token_secret,
            )
            if settings.proxmox_template_vmid <= 0:
                raise RuntimeError("CARPENTER_PROXMOX_TEMPLATE_VMID must reference a prepared cloud-init template.")
            created = []
            next_vmid = adapter.next_vmid()
            for index in range(request["vm_count"]):
                vmid = next_vmid + index
                name = f"{request['name']}-{index + 1:03d}"
                cloned = adapter.clone_vm(
                    settings.proxmox_node, settings.proxmox_template_vmid, vmid, name,
                    request["vcpu_per_vm"], request["memory_gb_per_vm"] * 1024,
                )
                start_task = adapter.start_vm(settings.proxmox_node, vmid)
                created.append({**cloned, "start_task": start_task})
            results["components"]["iaas"] = {"created_vms": created}

        if model in ("paas", "hybrid"):
            image = request.get("container_image")
            if not image:
                raise RuntimeError("container_image is required for PaaS deployment.")
            adapter = KubernetesAdapter(settings.kubernetes_api_url, settings.kubernetes_token)
            deployment = adapter.create_deployment(
                request["namespace"], request["name"], image,
                request["vm_count"], request["container_port"],
            )
            results["components"]["paas"] = {"deployment": deployment}

        return results
