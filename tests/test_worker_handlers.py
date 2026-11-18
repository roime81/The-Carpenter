from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from handlers import (execute, installed_capabilities, kubernetes_deploy,
                      proxmox_inventory, kubernetes_inventory)
from app.iac_engine import compile_iac_bundle


class WorkerCapabilityTests(unittest.TestCase):
    def test_provider_functions_are_not_advertised_without_worker_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            capabilities = installed_capabilities()
        self.assertIn("discovery.host_inventory", capabilities)
        self.assertNotIn("compute.proxmox_deploy", capabilities)
        self.assertNotIn("platform.kubernetes_deploy", capabilities)
        self.assertNotIn("gamgee.bootstrap", capabilities)

    def test_proxmox_function_requires_complete_local_configuration(self):
        values = {
            "CARPENTER_PROXMOX_URL": "https://pve.example.test:8006",
            "CARPENTER_PROXMOX_TOKEN_ID": "carpenter@pve!worker",
            "CARPENTER_PROXMOX_TOKEN_SECRET": "secret",
            "CARPENTER_PROXMOX_NODE": "pve-01",
            "CARPENTER_PROXMOX_TEMPLATE_VMID": "9000",
        }
        with patch.dict(os.environ, values, clear=True):
            capabilities = installed_capabilities()
        self.assertEqual(capabilities["compute.proxmox_deploy"], "1.0.0")

    def test_kubernetes_and_gamgee_are_independent_worker_capabilities(self):
        with patch.dict(os.environ, {
            "CARPENTER_KUBERNETES_API_URL": "https://kube.example.test:6443",
            "CARPENTER_KUBERNETES_TOKEN": "kube-token",
        }, clear=True):
            capabilities = installed_capabilities()
        self.assertEqual(capabilities["platform.kubernetes_deploy"], "1.0.0")
        self.assertNotIn("gamgee.bootstrap", capabilities)

        with patch.dict(os.environ, {
            "CARPENTER_GAMGEE_INSTALLER_URL": "https://gamgee.example.test/bootstrap",
            "CARPENTER_GAMGEE_INSTALLER_TOKEN": "hmac-secret",
        }, clear=True):
            capabilities = installed_capabilities()
        self.assertEqual(capabilities["gamgee.bootstrap"], "1.0.0")
        self.assertNotIn("platform.kubernetes_deploy", capabilities)

    def test_worker_refuses_unconfigured_provider_function(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                execute("compute.proxmox_deploy", "1.0.0", {})

    def test_kubernetes_worker_applies_only_compiler_generated_manifests(self):
        request = {
            "destination": "own_cloud", "service_model": "paas", "vm_count": 2,
            "vcpu_per_vm": 2, "memory_gb_per_vm": 4, "disk_gb_per_vm": 40,
            "high_availability": False, "name": "test-api", "namespace": "test",
            "container_image": "nginx:stable", "container_port": 8080,
        }
        bundle = compile_iac_bundle(
            "12345678-1234-1234-1234-123456789abc", request, None,
            {"gamgee": [], "proxmox": [], "kubernetes": ["worker-kube"]},
        )
        manifests = [
            item["spec"] for item in bundle["resources"]
            if item["provider"] == "kubernetes"
        ]
        with patch("handlers._kubernetes_apply", side_effect=[{"kind": "Deployment"}, {"kind": "Service"}]) as apply:
            result = kubernetes_deploy({
                "deployment_id": bundle["deployment_id"],
                "iac_fingerprint": bundle["fingerprint"],
                "manifests": manifests,
            })
        self.assertEqual(result["execution_status"], "succeeded")
        self.assertEqual(apply.call_count, 2)

    def test_proxmox_inventory_emits_hypervisor_vm_network_and_storage_graph(self):
        inventory_rows = [
            {"type": "node", "node": "pve-01", "status": "online", "maxcpu": 16, "maxmem": 68719476736},
            {"type": "qemu", "node": "pve-01", "vmid": 101, "name": "web-01", "status": "running", "maxcpu": 4},
            {"type": "storage", "node": "pve-01", "storage": "local-lvm", "status": "active", "total": 100000},
        ]
        with patch("handlers._proxmox_request", side_effect=[
            inventory_rows,
            {"net0": "virtio=BC:24:11:22:33:44,bridge=vmbr0", "scsi0": "local-lvm:vm-101-disk-0,size=40G"},
        ]) as request:
            result = proxmox_inventory({})

        resources = {(item["resource_type"], item["native_id"]): item for item in result["observed_resources"]}
        self.assertIn(("hypervisor_node", "nodes/pve-01"), resources)
        self.assertIn(("virtual_machine", "qemu/101"), resources)
        self.assertIn(("network", "network/pve-01/vmbr0"), resources)
        self.assertIn(("storage_volume", "volume/pve-01/local-lvm:vm-101-disk-0"), resources)
        relations = {(item["source_native_id"], item["target_native_id"], item["relation"])
                     for item in result["observed_relationships"]}
        self.assertIn(("nodes/pve-01", "qemu/101", "hosts"), relations)
        self.assertIn(("qemu/101", "network/pve-01/vmbr0", "connected_to"), relations)
        self.assertIn(("qemu/101", "volume/pve-01/local-lvm:vm-101-disk-0", "uses_storage"), relations)
        self.assertEqual(request.call_count, 2)

    def test_kubernetes_inventory_emits_namespaced_workloads_services_pods_and_claims(self):
        responses = [
            {"items": [{
                "metadata": {"name": "web", "uid": "deployment-uid", "generation": 2},
                "spec": {
                    "replicas": 2,
                    "selector": {"matchLabels": {"app": "web"}},
                    "template": {"spec": {"containers": [{"image": "nginx:stable"}]}},
                },
                "status": {"readyReplicas": 2},
            }]},
            {"items": [{
                "metadata": {"name": "web"},
                "spec": {
                    "type": "ClusterIP", "clusterIP": "10.96.0.10",
                    "selector": {"app": "web"},
                    "ports": [{"port": 80, "targetPort": 8080}],
                },
            }]},
            {"items": [{
                "metadata": {"name": "web-data"},
                "spec": {
                    "storageClassName": "fast",
                    "resources": {"requests": {"storage": "10Gi"}},
                    "accessModes": ["ReadWriteOnce"],
                },
                "status": {"phase": "Bound"},
            }]},
            {"items": [{
                "metadata": {"name": "web-pod-1", "ownerReferences": [{"name": "web-replicaset"}]},
                "spec": {"nodeName": "kube-node-01"},
                "status": {
                    "phase": "Running", "podIP": "10.1.1.10",
                    "containerStatuses": [{"restartCount": 2}],
                },
            }]},
        ]
        with patch.dict(os.environ, {
            "CARPENTER_KUBERNETES_API_URL": "https://kube.example.test:6443",
            "CARPENTER_KUBERNETES_TOKEN": "worker-token",
            "CARPENTER_KUBERNETES_NAMESPACE": "production",
        }, clear=True), patch("handlers._kubernetes_read", side_effect=responses) as request:
            result = kubernetes_inventory({})

        resources = {(item["resource_type"], item["native_id"]): item for item in result["observed_resources"]}
        self.assertIn(("cluster", "api/kube.example.test:6443"), resources)
        self.assertIn(("namespace", "namespace/production"), resources)
        self.assertEqual(resources[("workload", "deployments/production/web")]["status"], "ready")
        self.assertIn(("service", "services/production/web"), resources)
        self.assertIn(("storage_volume", "pvc/production/web-data"), resources)
        self.assertIn(("workload_instance", "pods/production/web-pod-1"), resources)
        self.assertIn(("compute_host", "nodes/kube-node-01"), resources)
        relations = {(item["source_native_id"], item["target_native_id"], item["relation"])
                     for item in result["observed_relationships"]}
        self.assertIn(("services/production/web", "deployments/production/web", "routes_to"), relations)
        self.assertIn(("pods/production/web-pod-1", "nodes/kube-node-01", "scheduled_on"), relations)
        self.assertEqual(request.call_count, 4)

    def test_kubernetes_worker_rejects_tampered_generated_manifests(self):
        request = {
            "destination": "own_cloud", "service_model": "paas", "vm_count": 2,
            "vcpu_per_vm": 2, "memory_gb_per_vm": 4, "disk_gb_per_vm": 40,
            "high_availability": False, "name": "test-api", "namespace": "test",
            "container_image": "nginx:stable", "container_port": 8080,
        }
        bundle = compile_iac_bundle(
            "12345678-1234-1234-1234-123456789abc", request, None,
            {"gamgee": [], "proxmox": [], "kubernetes": ["worker-kube"]},
        )
        manifests = [
            item["spec"] for item in bundle["resources"]
            if item["provider"] == "kubernetes"
        ]
        manifests[1]["spec"]["selector"] = {"app": "other-app"}
        with patch("handlers._kubernetes_apply") as apply:
            with self.assertRaises(ValueError):
                kubernetes_deploy({
                    "deployment_id": bundle["deployment_id"],
                    "iac_fingerprint": bundle["fingerprint"],
                    "manifests": manifests,
                })
            apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
