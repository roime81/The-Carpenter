from __future__ import annotations

import copy
import unittest

import yaml

from app.iac_engine import compile_iac_bundle, validate_iac_bundle


class IaCEngineTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "destination": "own_cloud",
            "service_model": "paas",
            "vm_count": 3,
            "vcpu_per_vm": 2,
            "memory_gb_per_vm": 4,
            "disk_gb_per_vm": 40,
            "high_availability": False,
            "name": "inventory-api",
            "namespace": "production",
            "container_image": "ghcr.io/example/inventory:v1",
            "container_port": 8080,
        }
        self.workers = {"gamgee": [], "proxmox": [], "kubernetes": ["kube-worker-01"]}

    def test_compiles_user_intent_to_kubernetes_yaml_without_user_supplied_yaml(self):
        bundle = compile_iac_bundle(
            "12345678-1234-1234-1234-123456789abc",
            self.request,
            None,
            self.workers,
        )
        self.assertEqual(bundle["resource_count"], 2)
        self.assertTrue(bundle["validation"]["schema_valid"])
        artifact = bundle["artifacts"][0]
        documents = list(yaml.safe_load_all(artifact["content"]))
        self.assertEqual([item["kind"] for item in documents], ["Deployment", "Service"])
        self.assertEqual(documents[0]["spec"]["replicas"], 3)
        self.assertEqual(documents[0]["spec"]["template"]["spec"]["containers"][0]["image"],
                         "ghcr.io/example/inventory:v1")
        self.assertEqual(validate_iac_bundle(bundle)["fingerprint"], bundle["fingerprint"])

    def test_compiler_output_is_deterministic(self):
        deployment_id = "12345678-1234-1234-1234-123456789abc"
        first = compile_iac_bundle(deployment_id, self.request, None, self.workers)
        second = compile_iac_bundle(deployment_id, self.request, None, self.workers)
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["artifacts"][0]["sha256"], second["artifacts"][0]["sha256"])

    def test_bundle_tampering_is_detected(self):
        bundle = compile_iac_bundle(
            "12345678-1234-1234-1234-123456789abc",
            self.request,
            None,
            self.workers,
        )
        changed = copy.deepcopy(bundle)
        changed["resources"][0]["spec"]["spec"]["replicas"] = 999
        with self.assertRaises(ValueError):
            validate_iac_bundle(changed)

    def test_compiler_never_embeds_credentials_or_executable_code(self):
        bundle = compile_iac_bundle(
            "12345678-1234-1234-1234-123456789abc",
            self.request,
            None,
            self.workers,
        )
        self.assertFalse(bundle["validation"]["provider_secrets_embedded"])
        self.assertFalse(bundle["validation"]["generated_code_embedded"])
        combined = str(bundle).lower()
        self.assertNotIn("password", combined)
        self.assertNotIn("shell:", combined)
        self.assertNotIn("command:", combined)


if __name__ == "__main__":
    unittest.main()
