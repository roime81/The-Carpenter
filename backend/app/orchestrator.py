from __future__ import annotations

import re
from typing import Any

from app import store
from app.config import settings
from app.functions import register_builtin_functions
from app.llm import ModelGateway
from app.runtime.faas import FunctionRuntime


class CarpenterOrchestrator:
    """Conversation coordinator. The model extracts intent; policy and functions decide."""

    def __init__(self) -> None:
        self.runtime = FunctionRuntime()
        self.brain = ModelGateway()
        register_builtin_functions(self.runtime)

    def respond(self, session_id: str, prompt: str) -> str:
        state = store.get_state(session_id)
        agents = store.list_agents()
        phase = state.get("phase", "connect")
        slots = self.brain.extract_slots(prompt)

        if not agents:
            # Preserve explicit requirements while the user is connecting the data plane.
            numbers = re.findall(r"\b\d+\b", prompt)
            if "vm_count" in slots:
                state["vm_count"] = slots["vm_count"]
            elif numbers and "vm" in prompt.lower():
                state["vm_count"] = min(max(int(numbers[0]), 1), 10000)
            if "destination" in slots:
                state["destination"] = slots["destination"]
            if "service_model" in slots:
                state["service_model"] = slots["service_model"]
            state["phase"] = "connect"
            store.set_state(session_id, state)
            return (
                "Let's start with your infrastructure. I need to verify the servers before "
                "designing a cloud. Install the Python Carpenter Node Agent on each server and "
                "point it to this Carpenter control-plane URL. Once a node reports in, I can "
                "inspect its CPU, memory, storage and network inventory. A ping alone is not "
                "enough to prove that a server is manageable.\n\n"
                "For this first version, discovery is limited to explicitly enrolled nodes; "
                "I will not scan arbitrary networks or execute commands across your estate."
            )

        capacity_result = self.runtime.invoke(
            "assessment.capacity",
            {"hosts": agents},
            idempotency_key=None,
        )["output"]

        if phase in ("connect", "await_vm_count"):
            vm_count = slots.get("vm_count") or state.get("vm_count")
            if not vm_count:
                numbers = re.findall(r"\b\d+\b", prompt)
                if phase == "await_vm_count" and numbers:
                    vm_count = min(max(int(numbers[0]), 1), 10000)
            if vm_count:
                state["vm_count"] = vm_count
                if slots.get("destination"):
                    state["destination"] = slots["destination"]
                if slots.get("service_model"):
                    state["service_model"] = slots["service_model"]
                if state.get("destination"):
                    state["phase"] = "await_service_model"
                    store.set_state(session_id, state)
                    target = "GAMGEE Cloud" if state["destination"] == "gamgee" else "your own cloud"
                    return f"I have recorded {vm_count} VM(s). The target is **{target}**. Should I design **IaaS**, **PaaS**, or **hybrid**?"
                state["phase"] = "await_destination"
                store.set_state(session_id, state)
                return (
                    f"I have recorded a request for {vm_count} VM(s). "
                    "Would you like me to **onboard GAMGEE Cloud**, or build **your own cloud**?"
                )

            state["phase"] = "await_vm_count"
            store.set_state(session_id, state)
            return (
                f"Discovery has received {capacity_result['host_count']} enrolled server(s). "
                f"Preliminary inventory: {capacity_result['total_cpu_cores']} CPU cores, "
                f"{capacity_result['total_memory_gb']} GiB total memory and "
                f"{capacity_result['available_memory_gb']} GiB currently available. "
                "This is an inventory estimate, not yet a placement guarantee.\n\n"
                "How many virtual machines would you like to create? You can also tell me "
                "the workload and I will help estimate the number."
            )

        if phase == "await_destination":
            lowered = prompt.lower()
            destination = slots.get("destination")
            if destination == "gamgee" or "gamgee" in lowered:
                state["destination"] = "gamgee"
            elif destination == "own_cloud" or any(word in lowered for word in ("own cloud", "my cloud", "custom", "independent")):
                state["destination"] = "own_cloud"
            else:
                return "Please choose **GAMGEE Cloud** or **your own cloud**. Both remain available."
            state["phase"] = "await_service_model"
            store.set_state(session_id, state)
            target = "GAMGEE Cloud" if state["destination"] == "gamgee" else "your own cloud"
            return f"Understood. The target is **{target}**. Should I design **IaaS**, **PaaS**, or a **hybrid**?"

        if phase == "await_service_model":
            lowered = prompt.lower()
            model = slots.get("service_model")
            if model not in ("iaas", "paas", "hybrid"):
                if "hybrid" in lowered:
                    model = "hybrid"
                elif "paas" in lowered:
                    model = "paas"
                elif "iaas" in lowered:
                    model = "iaas"
            if model not in ("iaas", "paas", "hybrid"):
                return "Choose **IaaS**, **PaaS**, or **hybrid**. I can explain the trade-offs before you decide."

            state["service_model"] = model
            state["phase"] = "plan_review"
            store.set_state(session_id, state)
            plan = self.runtime.invoke(
                "planning.deployment",
                {
                    "capacity": capacity_result,
                    "destination": state["destination"],
                    "service_model": model,
                    "vm_count": state.get("vm_count", 1),
                    "vcpu_per_vm": 2,
                    "memory_gb_per_vm": 4,
                },
            )["output"]
            state["last_plan"] = plan
            store.set_state(session_id, state)
            fit = "fits the preliminary CPU and memory estimate" if plan["capacity_fit"] else "exceeds the preliminary capacity estimate"
            destination = "GAMGEE Cloud" if plan["destination"] == "gamgee" else "your own cloud"
            return (
                f"**Assessment plan prepared**\n\n"
                f"- Destination: {destination}\n"
                f"- Cloud model: {model.upper()}\n"
                f"- VMs requested: {plan['vm_count']} × {plan['vcpu_per_vm']} vCPU / "
                f"{plan['memory_gb_per_vm']} GiB RAM\n"
                f"- Aggregate request: {plan['requested_vcpu']} vCPU / "
                f"{plan['requested_memory_gb']} GiB RAM\n"
                f"- Capacity: {fit}\n\n"
                "This is a planning result only. The next engineering milestone is to connect "
                "a verified hypervisor/cloud adapter and produce an approval-ready deployment "
                "plan. No resources have been changed."
            )

        return (
            "I have the current assessment context. Tell me what you would like to adjust, "
            "or start a new deployment conversation. Infrastructure changes remain disabled "
            "until a compatible execution adapter and approval workflow are enabled."
        )

    def function_catalogue(self) -> list[dict[str, Any]]:
        return self.runtime.catalogue()
