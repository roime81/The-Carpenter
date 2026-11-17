from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from handlers import execute, installed_capabilities, kubernetes_deploy
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
