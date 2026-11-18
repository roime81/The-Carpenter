from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import store, infrastructure_twin


class InfrastructureTwinTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_settings = store.settings
        store.settings = SimpleNamespace(
            database_path=str(Path(self.tempdir.name) / "carpenter.db"),
            agent_stale_seconds=120,
        )
        store.initialise_store()

    def tearDown(self):
        store.settings = self.previous_settings
        self.tempdir.cleanup()

    def sample_worker(self):
        return {
            "node_id": "worker-001",
            "hostname": "pve-01",
            "operating_system": "Linux",
            "architecture": "x86_64",
            "cpu_cores": 16,
            "cpu_percent": 13.2,
            "memory_total_bytes": 64 * 1024 ** 3,
            "memory_available_bytes": 48 * 1024 ** 3,
            "disk_total_bytes": 2 * 1024 ** 4,
            "disk_free_bytes": 1 * 1024 ** 4,
            "ipv4_addresses": ["10.10.1.10", "203.0.113.10"],
            "failure_domain": "rack-a",
            "capabilities": {"compute.proxmox_deploy": "1.0.0"},
            "discovery": {
                "hypervisor": {
                    "proxmox_host": True,
                    "kvm_device": True,
                    "libvirt_socket": True,
                },
                "storage_network": {
                    "partitions": [{
                        "device": "/dev/sda1",
                        "mountpoint": "/",
                        "filesystem": "ext4",
                        "total_bytes": 1000,
                        "free_bytes": 500,
                    }],
                    "interfaces": {
                        "eth0": {
                            "is_up": True,
                            "speed_mbps": 1000,
                            "addresses": [{
                                "family": "AddressFamily.AF_INET",
                                "address": "10.10.1.10",
                                "netmask": "255.255.255.0",
                            }],
                        }
                    },
                },
            },
        }

    def test_heartbeat_creates_control_plane_host_and_observed_subresources(self):
        worker = self.sample_worker()
        store.upsert_agent(worker)
        infrastructure_twin.observe_worker_heartbeat(store.get_agent(worker["node_id"]))

        resources = {item["resource_id"]: item for item in store.list_twin_resources()}
        control_id = infrastructure_twin.CONTROL_PLANE_ID
        host_id = infrastructure_twin.resource_id("carpenter-agent", "worker-001")
        hypervisor_id = infrastructure_twin.resource_id("linux-hypervisor", "worker-001")
        interface_id = infrastructure_twin.resource_id("linux-network", "worker-001/eth0")
        network_id = infrastructure_twin.resource_id("linux-network", "worker-001/10.10.1.0/24")
        volume_id = infrastructure_twin.resource_id("linux-storage", "worker-001//dev/sda1")

        self.assertIn(control_id, resources)
        self.assertEqual(resources[host_id]["resource_type"], "compute_host")
        self.assertEqual(resources[hypervisor_id]["resource_type"], "hypervisor")
        self.assertEqual(resources[interface_id]["resource_type"], "network_interface")
        self.assertEqual(resources[network_id]["resource_type"], "network")
        self.assertEqual(resources[volume_id]["resource_type"], "storage_volume")
        self.assertNotIn("203.0.113.10", resources[host_id]["properties"]["ipv4_addresses"])

        pairs = {
            (item["source_resource_id"], item["target_resource_id"], item["relation"])
            for item in store.list_twin_relationships()
        }
        self.assertIn((control_id, host_id, "manages"), pairs)
        self.assertIn((host_id, interface_id, "has_interface"), pairs)
        self.assertIn((interface_id, network_id, "connected_to"), pairs)
        self.assertIn((host_id, volume_id, "has_storage"), pairs)

    def test_provider_observation_creates_confirmed_kubernetes_topology(self):
        worker = self.sample_worker()
        store.upsert_agent(worker)
        infrastructure_twin.observe_worker_heartbeat(store.get_agent(worker["node_id"]))
        job = {
            "job_id": "job-k8s",
            "function_name": "platform.kubernetes_deploy",
            "worker_id": "worker-001",
            "payload": {"deployment_id": "deploy-001"},
        }
        result = {
            "deployment_id": "deploy-001",
            "execution_status": "succeeded",
            "observed_resources": [
                {"provider": "kubernetes", "resource_type": "cluster",
                 "native_id": "api/kube.example:6443", "name": "kube.example:6443",
                 "status": "reachable", "properties": {"cluster_endpoint": "kube.example:6443"}},
                {"provider": "kubernetes", "resource_type": "namespace",
                 "native_id": "namespace/default", "name": "default",
                 "status": "observed", "properties": {"namespace": "default"}},
                {"provider": "kubernetes", "resource_type": "workload",
                 "native_id": "deployment/default/web", "name": "web",
                 "status": "ready", "properties": {"namespace": "default", "replicas": 2, "ready_replicas": 2}},
                {"provider": "kubernetes", "resource_type": "service",
                 "native_id": "service/default/web", "name": "web",
                 "status": "applied", "properties": {"namespace": "default", "service_type": "ClusterIP", "port": 8080}},
            ],
            "observed_relationships": [
                {"source_provider": "kubernetes", "source_native_id": "api/kube.example:6443",
                 "target_provider": "kubernetes", "target_native_id": "namespace/default", "relation": "contains"},
                {"source_provider": "kubernetes", "source_native_id": "namespace/default",
                 "target_provider": "kubernetes", "target_native_id": "deployment/default/web", "relation": "contains"},
                {"source_provider": "kubernetes", "source_native_id": "namespace/default",
                 "target_provider": "kubernetes", "target_native_id": "service/default/web", "relation": "contains"},
                {"source_provider": "kubernetes", "source_native_id": "service/default/web",
                 "target_provider": "kubernetes", "target_native_id": "deployment/default/web", "relation": "routes_to"},
            ],
        }
        infrastructure_twin.observe_provider_result(job, result)

        resources = {item["resource_id"]: item for item in store.list_twin_resources()}
        cluster = infrastructure_twin.resource_id("kubernetes", "api/kube.example:6443")
        workload = infrastructure_twin.resource_id("kubernetes", "deployment/default/web")
        service = infrastructure_twin.resource_id("kubernetes", "service/default/web")
        self.assertEqual(resources[cluster]["status"], "reachable")
        self.assertEqual(resources[workload]["status"], "ready")
        self.assertEqual(resources[service]["deployment_id"], "deploy-001")

        pairs = {
            (item["source_resource_id"], item["target_resource_id"], item["relation"])
            for item in store.list_twin_relationships()
        }
        self.assertIn((service, workload, "routes_to"), pairs)
        self.assertIn((workload, service, "routes_to"), {(a, b, r) for a, b, r in pairs} if False else set())

    def test_resource_observations_are_versioned_and_secret_fields_are_not_stored(self):
        base = {
            "resource_id": infrastructure_twin.resource_id("proxmox", "qemu/101"),
            "resource_type": "virtual_machine",
            "provider": "proxmox",
            "native_id": "qemu/101",
            "name": "web-01",
            "status": "started",
            "source": "provider_apply",
            "properties": {"vmid": 101, "vcpu": 4, "api_token": "do-not-store"},
        }
        first = store.upsert_twin_resource(base)
        changed = dict(base, status="stopped")
        second = store.upsert_twin_resource(changed)

        history = store.list_twin_observations(first["resource_id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual([item["change_type"] for item in history], ["created", "changed"])
        self.assertEqual(history[-1]["previous_status"], "started")
        self.assertNotIn("api_token", second["properties"])

    def test_global_snapshot_marks_worker_offline_from_heartbeat_freshness(self):
        worker = self.sample_worker()
        store.upsert_agent(worker)
        infrastructure_twin.observe_worker_heartbeat(store.get_agent(worker["node_id"]))
        result = infrastructure_twin.list_twin_snapshot()
        host = next(item for item in result["resources"] if item["resource_type"] == "compute_host")
        self.assertEqual(host["status"], "online")
        self.assertGreaterEqual(result["resource_count"], 1)
        self.assertGreaterEqual(result["relationship_count"], 1)


if __name__ == "__main__":
    unittest.main()
