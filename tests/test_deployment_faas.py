from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import store
from app.deployment_engine import DeploymentEngine
from app.deployment_store import create, approve, set_status, link_job, reconcile_status
from app.worker_catalogue import register_worker_functions


GIB = 1024 ** 3


def proxmox_worker(node_id: str, domain: str) -> dict:
    return {
        "node_id": node_id,
        "hostname": node_id,
        "online": True,
        "failure_domain": domain,
        "cpu_cores": 32,
        "memory_total_bytes": 256 * GIB,
        "memory_available_bytes": 240 * GIB,
        "disk_total_bytes": 2 * 1024 ** 4,
        "disk_free_bytes": 2 * 1024 ** 4,
        "capabilities": {"compute.proxmox_deploy": "1.0.0"},
        "discovery": {"hypervisor": {"proxmox_host": True, "kvm_device": True}},
    }


class DeploymentFaasTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_settings = store.settings
        store.settings = SimpleNamespace(
            database_path=str(Path(self.tempdir.name) / "carpenter.db"),
            agent_stale_seconds=120,
        )
        store.initialise_store()
        register_worker_functions()

    def tearDown(self):
        store.settings = self.previous_settings
        self.tempdir.cleanup()

    def test_plan_selects_workers_by_provider_function_capability(self):
        hosts = [proxmox_worker("pve-worker-01", "rack-a")]
        request = {
            "destination": "own_cloud",
            "service_model": "iaas",
            "vm_count": 2,
            "vcpu_per_vm": 4,
            "memory_gb_per_vm": 16,
            "disk_gb_per_vm": 80,
            "high_availability": False,
            "name": "app-node",
            "namespace": "default",
            "container_image": None,
            "container_port": 8080,
        }
        plan = DeploymentEngine().build_plan(request, hosts)
        self.assertTrue(plan["adapter_ready"])
        self.assertTrue(plan["capacity_ready"])
        self.assertEqual(plan["execution_workers"]["proxmox"], ["pve-worker-01"])

    def test_approved_vm_deployment_is_enqueued_as_one_job_per_vm(self):
        host = proxmox_worker("pve-worker-01", "rack-a")
        store.upsert_agent(host)
        request = {
            "destination": "own_cloud",
            "service_model": "iaas",
            "vm_count": 2,
            "vcpu_per_vm": 4,
            "memory_gb_per_vm": 16,
            "disk_gb_per_vm": 80,
            "high_availability": False,
            "name": "app-node",
            "namespace": "default",
            "container_image": None,
            "container_port": 8080,
        }
        plan = DeploymentEngine().build_plan(request, [host])
        self.assertTrue(plan["ready_to_execute_after_approval"])
        deployment = create("own_cloud", "iaas", plan)
        approve(deployment["deployment_id"], "test-owner")
        set_status(deployment["deployment_id"], "executing")

        dispatch = DeploymentEngine().execute(deployment["deployment_id"], plan)
        self.assertEqual(dispatch["execution_status"], "queued")
        self.assertEqual(len(dispatch["queued_jobs"]), 2)
        self.assertTrue(all(
            item["function_name"] == "compute.proxmox_deploy"
            and item["target_worker_id"] == "pve-worker-01"
            and len(item["payload"]["vms"]) == 1
            for item in dispatch["queued_jobs"]
        ))

        for item in dispatch["queued_jobs"]:
            link_job(deployment["deployment_id"], item["job_id"], item["component"])

        # Complete both targeted jobs through the same worker lease protocol.
        for _ in dispatch["queued_jobs"]:
            claimed = store.claim_job("pve-worker-01", lease_seconds=600)
            self.assertIsNotNone(claimed)
            self.assertTrue(store.complete_job(
                claimed["job_id"], "pve-worker-01", claimed["lease_token"],
                {"execution_status": "succeeded"},
            ))

        final = reconcile_status(deployment["deployment_id"])
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(len(final["jobs"]), 2)


if __name__ == "__main__":
    unittest.main()
