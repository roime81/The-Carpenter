from __future__ import annotations

import re
import uuid
from typing import Any

from app import store
from app.deployment_engine import DeploymentEngine
from app.deployment_store import create as create_deployment_record
from app.functions import register_builtin_functions
from app.llm import ModelGateway
from app.runtime.faas import FunctionRuntime
from app.canvas_runtime import attach_canvas_artifacts


DISCOVERY_FUNCTIONS = (
    "discovery.host_inventory",
    "discovery.hypervisor_probe",
    "discovery.storage_network",
)


class CarpenterOrchestrator:
    """AI Cloud Deployment Agent: interpret, discover, plan, compile IaC and orchestrate FaaS execution."""

    def __init__(self) -> None:
        self.runtime = FunctionRuntime()
        self.brain = ModelGateway()
        register_builtin_functions(self.runtime)

    @staticmethod
    def _number_from_prompt(prompt: str, allow_first_number: bool = False) -> int | None:
        match = re.search(
            r"\b(\d+)\s*(?:vms?|virtual\s+machines?|replicas?)\b",
            prompt,
            re.IGNORECASE,
        )
        if match:
            return min(max(int(match.group(1)), 1), 10000)
        if allow_first_number:
            match = re.search(r"\b(\d+)\b", prompt)
            if match:
                return min(max(int(match.group(1)), 1), 10000)
        return None

    @staticmethod
    def _deterministic_sizing(prompt: str) -> dict[str, Any]:
        """Extract only explicit sizing terms when no LLM slot is available."""
        patterns = {
            "vcpu_per_vm": r"\b(\d+)\s*(?:vcpus?|virtual\s+cpus?|cores?)\b",
            "memory_gb_per_vm": r"\b(\d+)\s*(?:gb|gib)\s*(?:of\s*)?(?:ram|memory)\b",
            "disk_gb_per_vm": r"\b(\d+)\s*(?:gb|gib)\s*(?:of\s*)?(?:disk|storage)\b",
            "container_port": r"\bport\s*(\d{1,5})\b",
        }
        limits = {
            "vcpu_per_vm": (1, 256),
            "memory_gb_per_vm": (1, 4096),
            "disk_gb_per_vm": (1, 100000),
            "container_port": (1, 65535),
        }
        result: dict[str, Any] = {}
        for field, pattern in patterns.items():
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                minimum, maximum = limits[field]
                if minimum <= value <= maximum:
                    result[field] = value
        return result

    @staticmethod
    def _destination(prompt: str, slots: dict[str, Any]) -> str | None:
        value = slots.get("destination")
        if value in ("gamgee", "own_cloud"):
            return value
        lowered = prompt.lower()
        if "gamgee" in lowered:
            return "gamgee"
        if any(word in lowered for word in ("own cloud", "my cloud", "custom cloud", "independent cloud")):
            return "own_cloud"
        return None

    @staticmethod
    def _service_model(prompt: str, slots: dict[str, Any]) -> str | None:
        value = slots.get("service_model")
        if value in ("iaas", "paas", "hybrid"):
            return value
        lowered = prompt.lower()
        if "hybrid" in lowered:
            return "hybrid"
        if "paas" in lowered:
            return "paas"
        if "iaas" in lowered:
            return "iaas"
        return None

    @staticmethod
    def _queue_new_node_discovery(
        session_id: str, state: dict[str, Any], agents: list[dict[str, Any]]
    ) -> None:
        discovered = set(state.get("discovery_nodes", []))
        new_nodes = [agent for agent in agents if agent["node_id"] not in discovered]
        for agent in new_nodes:
            for function_name in DISCOVERY_FUNCTIONS:
                job = store.enqueue_job(
                    function_name,
                    "1.0.0",
                    {"session_id": session_id, "canvas_stage": "discovery", "worker_id": agent["node_id"]},
                    max_attempts=3,
                    idempotency_key=f"prompt-discovery-{session_id}-{agent['node_id']}-{function_name}-{uuid.uuid4()}",
                    target_worker_id=agent["node_id"],
                )
                store.record_event("faas.job.enqueued", job["job_id"], {
                    "session_id": session_id,
                    "function_name": function_name,
                    "function_version": "1.0.0",
                    "worker_id": agent["node_id"],
                })
            discovered.add(agent["node_id"])
        state["discovery_nodes"] = sorted(discovered)

    def _create_plan(self, session_id: str, state: dict[str, Any], agents: list[dict[str, Any]]) -> str:
        request = {
            "destination": state["destination"],
            "service_model": state["service_model"],
            "vm_count": state.get("vm_count", 1),
            "vcpu_per_vm": state.get("vcpu_per_vm", 2),
            "memory_gb_per_vm": state.get("memory_gb_per_vm", 4),
            "disk_gb_per_vm": state.get("disk_gb_per_vm", 40),
            "high_availability": bool(state.get("high_availability", False)),
            "name": state.get("name", "carpenter-app"),
            "namespace": state.get("namespace", "default"),
            "container_image": state.get("container_image"),
            "container_port": state.get("container_port", 8080),
        }
        plan = DeploymentEngine().build_plan(request, agents)
        plan["canvas_session_id"] = session_id
        plan = attach_canvas_artifacts(plan, state.get("last_prompt", ""))
        record = create_deployment_record(
            request["destination"], request["service_model"], plan
        )
        state["deployment_id"] = record["deployment_id"]
        state["last_plan"] = plan
        state["phase"] = "plan_review"
        store.set_state(session_id, state)
        store.record_event("prompt.deployment.plan.created", record["deployment_id"], {
            "session_id": session_id,
            "destination": request["destination"],
            "service_model": request["service_model"],
            "iac_fingerprint": plan["iac_bundle"]["fingerprint"],
        })

        blockers: list[str] = []
        if not plan["capacity_ready"]:
            placement = plan.get("placement") or {}
            blockers.extend(placement.get("reasons", []))
            if not blockers:
                blockers.append("No online, eligible data-plane capacity was found.")
        if not plan["ha_ready"]:
            blockers.append("The requested HA topology is not sufficiently verified.")
        if not plan["adapter_ready"]:
            checks = plan["adapter_checks"]
            if request["destination"] == "gamgee" and not checks["gamgee_worker_available"]:
                blockers.append("No online worker is configured for the GAMGEE installer function.")
            if request["destination"] == "own_cloud":
                if request["service_model"] in ("iaas", "hybrid") and not checks["proxmox_worker_available"]:
                    blockers.append("No enrolled Proxmox worker advertises the configured deployment function.")
                if request["service_model"] in ("paas", "hybrid"):
                    if not checks["kubernetes_worker_available"]:
                        blockers.append("No worker advertises the configured Kubernetes deployment function.")
                    if not request.get("container_image"):
                        blockers.append("A container image is required for the PaaS component.")

        target = "GAMGEE Cloud" if request["destination"] == "gamgee" else "your own cloud"
        bundle = plan["iac_bundle"]
        artifact_names = [artifact["filename"] for artifact in bundle["artifacts"]]
        lines = [
            "**I have translated your request into an infrastructure plan.**",
            "",
            f"- Destination: {target}",
            f"- Cloud model: {request['service_model'].upper()}",
            f"- Requested VMs/replicas: {request['vm_count']}",
            f"- Online enrolled servers assessed: {plan['host_count']}",
            f"- Capacity check: {'passed' if plan['capacity_ready'] else 'not passed'}",
            f"- HA check: {'passed' if plan['ha_ready'] else 'not passed'}",
            f"- Provider workers: {'available' if plan['adapter_ready'] else 'not available'}",
            f"- Generated IaC resources: {bundle['resource_count']}",
            f"- IaC fingerprint: `{bundle['fingerprint']}`",
            f"- Deployment ID: `{record['deployment_id']}`",
            "",
            "**Generated resource graph**",
        ]
        lines.extend(
            f"- {resource['resource_id']} · {resource['provider']} / {resource['kind']}"
            for resource in bundle["resources"]
        )
        lines.extend(["", "**IaC artifacts generated internally**"])
        lines.extend(f"- `{name}`" for name in artifact_names)
        lines.append("You do not need to write YAML, Terraform, Ansible or provider API payloads by hand.")
        if blockers:
            lines.extend(["", "**Items to resolve before execution**"])
            lines.extend(f"- {item}" for item in blockers)
        else:
            lines.append("")
            lines.append("The generated resource graph passed validation and the initial readiness checks.")
            lines.append("")
            lines.append("Review the resources above. As an admin, say **approve** to approve this exact saved plan, then say **deploy** to execute it. You can also say **approve and deploy** to perform both explicit steps in one command.")
        lines.extend([
            "",
            "No infrastructure has changed yet. Before dispatch, The Carpenter revalidates the stored IaC fingerprint, capacity, placement and provider-worker assignment. Execution is asynchronous; say **status** to follow the result.",
        ])
        return "\n".join(lines)

    def respond(self, session_id: str, prompt: str) -> str:
        state = store.get_state(session_id)
        state["last_prompt"] = prompt[:8000]
        agents = store.list_agents(online_only=True)
        phase = state.get("phase", "connect")
        slots = self.brain.extract_slots(prompt)
        deterministic_sizing = self._deterministic_sizing(prompt)
        for key, value in deterministic_sizing.items():
            slots.setdefault(key, value)

        vm_count = slots.get("vm_count")
        if vm_count is None:
            vm_count = self._number_from_prompt(
                prompt, allow_first_number=(phase == "await_vm_count")
            )
        if vm_count is not None:
            state["vm_count"] = vm_count

        destination = self._destination(prompt, slots)
        if destination:
            state["destination"] = destination
        service_model = self._service_model(prompt, slots)
        if service_model:
            state["service_model"] = service_model
        for key in (
            "vcpu_per_vm", "memory_gb_per_vm", "disk_gb_per_vm",
            "container_port", "container_image", "name", "namespace",
        ):
            if key in slots:
                state[key] = slots[key]
        if "high_availability" in slots:
            state["high_availability"] = slots["high_availability"]
        lowered = prompt.lower()
        if "high_availability" in slots:
            state["high_availability"] = slots["high_availability"]
        elif any(term in lowered for term in ("no ha", "without ha", "disable ha", "not highly available", "no high availability")):
            state["high_availability"] = False
        elif any(term in lowered for term in ("high availability", "highly available", " ha ")):
            state["high_availability"] = True

        if not agents:
            state["phase"] = "connect"
            store.set_state(session_id, state)
            return (
                "Let's connect your data plane first. Install the Python Carpenter Node Agent "
                "on each server and point it to this Carpenter control-plane URL. The agent "
                "reports host inventory and advertises the read-only Python functions it can run.\n\n"
                "I have retained any VM count, destination or cloud-model requirements you already "
                "provided. A ping alone is not proof that a host is manageable; only explicitly "
                "enrolled nodes are assessed."
            )

        # Automatically queue detailed read-only discovery for any newly online node.
        self._queue_new_node_discovery(session_id, state, agents)

        if phase in ("connect", "await_vm_count"):
            if not state.get("vm_count"):
                state["phase"] = "await_vm_count"
                store.set_state(session_id, state)
                capacity = self.runtime.invoke(
                    "assessment.capacity", {"hosts": agents}
                )["output"]
                return (
                    f"I can see {capacity['host_count']} online enrolled server(s). "
                    f"Their preliminary capacity is {capacity['total_cpu_cores']} logical CPU cores "
                    f"and {capacity['total_memory_gb']} GiB RAM. Detailed discovery has been queued "
                    "for every online node.\n\n"
                    "How many virtual machines (or PaaS replicas) would you like?"
                )
            if not state.get("destination"):
                state["phase"] = "await_destination"
                store.set_state(session_id, state)
                return (
                    f"I have recorded {state['vm_count']} VM(s)/replica(s). Would you like me to "
                    "**onboard GAMGEE Cloud**, or build **your own cloud**?"
                )
            if not state.get("service_model"):
                state["phase"] = "await_service_model"
                store.set_state(session_id, state)
                return "Should I design **IaaS**, **PaaS**, or a **hybrid** cloud?"

        if phase == "await_destination" and not state.get("destination"):
            return "Please choose **GAMGEE Cloud** or **your own cloud**. Both paths are supported."

        if phase in ("await_destination", "await_service_model") and not state.get("service_model"):
            if state.get("destination") == "own_cloud":
                state["phase"] = "await_service_model"
                store.set_state(session_id, state)
            return "Should I design **IaaS**, **PaaS**, or a **hybrid** cloud?"

        if phase == "plan_review":
            deployment_id = state.get("deployment_id")
            if any(word in lowered for word in ("approve", "execute", "deploy now", "build now")):
                return (
                    f"The plan is saved as `{deployment_id}`. For safety, infrastructure changes "
                    "require an authenticated approval and execution call. Review the plan at "
                    f"`GET /api/v1/deployments/{deployment_id}`, then use the approve and execute "
                    "endpoints documented in the README."
                )
            previous = state.get("last_plan", {}).get("requested", {})
            current = {
                "destination": state.get("destination"),
                "service_model": state.get("service_model"),
                "vm_count": state.get("vm_count"),
                "vcpu_per_vm": state.get("vcpu_per_vm", 2),
                "memory_gb_per_vm": state.get("memory_gb_per_vm", 4),
                "disk_gb_per_vm": state.get("disk_gb_per_vm", 40),
                "high_availability": bool(state.get("high_availability", False)),
                "container_image": state.get("container_image"),
                "container_port": state.get("container_port", 8080),
                "name": state.get("name", "carpenter-app"),
                "namespace": state.get("namespace", "default"),
            }
            changed = any(previous.get(key) != value for key, value in current.items())
            if not changed:
                return f"The current deployment plan is `{deployment_id}`. Tell me the requirement you want to change; no resources have been changed."

        if state.get("destination") == "own_cloud" and state.get("service_model") in ("paas", "hybrid"):
            if not state.get("container_image") and phase != "await_container_image":
                state["phase"] = "await_container_image"
                store.set_state(session_id, state)
                return "What container image should I deploy for the PaaS component? For example, `nginx:stable`."

        if phase == "await_container_image" and state.get("container_image") is None:
            candidate = prompt.strip()
            if not candidate or len(candidate) > 512 or any(char.isspace() or ord(char) < 32 for char in candidate):
                return "Please provide one container image reference without spaces, such as `nginx:stable`."
            state["container_image"] = candidate

        if state.get("destination") and state.get("service_model") and state.get("vm_count"):
            return self._create_plan(session_id, state, agents)

        store.set_state(session_id, state)
        return "Tell me the VM count, cloud destination (GAMGEE or own cloud), and cloud model (IaaS, PaaS or hybrid)."

    def function_catalogue(self) -> list[dict[str, Any]]:
        return self.runtime.catalogue()
