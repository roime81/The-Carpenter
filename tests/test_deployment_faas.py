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
        self.assertEqual(plan["iac_bundle"]["schema_version"], "carpenter.iac/v1")
        self.assertTrue(plan["iac_validation"]["valid"])
        self.assertEqual(plan["iac_bundle"]["resource_count"], 2)

    def test_deployment_cannot_enter_executing_twice(self):
        host = proxmox_worker("pve-worker-01", "rack-a")
        request = {
            "destination": "own_cloud",
            "service_model": "iaas",
            "vm_count": 1,
            "vcpu_per_vm": 2,
            "memory_gb_per_vm": 4,
            "disk_gb_per_vm": 40,
            "high_availability": False,
            "name": "single-node",
            "namespace": "default",
            "container_image": None,
            "container_port": 8080,
        }
        plan = DeploymentEngine().build_plan(request, [host])
        deployment = create("own_cloud", "iaas", plan)
        approve(deployment["deployment_id"], "test-admin")

        first_transition = set_status(deployment["deployment_id"], "executing")
        self.assertEqual(first_transition["status"], "executing")
        duplicate_transition = set_status(deployment["deployment_id"], "executing")
        self.assertIsNone(duplicate_transition)
        failed_transition = set_status(deployment["deployment_id"], "failed")
        self.assertEqual(failed_transition["status"], "failed")

    def test_paas_ha_is_not_claimed_without_kubernetes_cluster_topology(self):
        kubernetes_workers = [
            {
                "node_id": "kube-worker-01",
                "hostname": "kube-worker-01",
                "online": True,
                "failure_domain": "rack-a",
                "cpu_cores": 8,
                "memory_total_bytes": 64 * GIB,
                "memory_available_bytes": 56 * GIB,
                "disk_total_bytes": 500 * GIB,
                "disk_free_bytes": 400 * GIB,
                "capabilities": {"platform.kubernetes_deploy": "1.0.0"},
            },
            {
                "node_id": "kube-worker-02",
                "hostname": "kube-worker-02",
                "online": True,
                "failure_domain": "rack-b",
                "cpu_cores": 8,
                "memory_total_bytes": 64 * GIB,
                "memory_available_bytes": 56 * GIB,
                "disk_total_bytes": 500 * GIB,
                "disk_free_bytes": 400 * GIB,
                "capabilities": {"platform.kubernetes_deploy": "1.0.0"},
            },
        ]
        request = {
            "destination": "own_cloud",
            "service_model": "paas",
            "vm_count": 3,
            "vcpu_per_vm": 2,
            "memory_gb_per_vm": 4,
            "disk_gb_per_vm": 20,
            "high_availability": True,
            "name": "frontend",
            "namespace": "production",
            "container_image": "nginx:stable",
            "container_port": 8080,
        }
        plan = DeploymentEngine().build_plan(request, kubernetes_workers)
        self.assertFalse(plan["ha_ready"])
        self.assertFalse(plan["ready_to_execute_after_approval"])
        self.assertIn("kubernetes_cluster_topology", plan["ha_assessments"])

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
            and item["payload"]["iac_fingerprint"] == plan["iac_bundle"]["fingerprint"]
            and item["payload"]["iac_resource"]["kind"] == "virtual_machine"
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
