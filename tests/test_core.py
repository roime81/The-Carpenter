import unittest

from app.functions import assess_capacity, build_deployment_plan, recommend_scaling
from app.llm import ModelGateway


class FunctionTests(unittest.TestCase):
    def test_capacity_keeps_twenty_percent_headroom(self):
        result = assess_capacity({"hosts": [{
            "cpu_cores": 16,
            "memory_total_bytes": 100 * 1024**3,
            "memory_available_bytes": 80 * 1024**3,
        }]})
        self.assertEqual(result["total_cpu_cores"], 16)
        self.assertEqual(result["allocatable_memory_gb"], 80.0)

    def test_plan_is_only_a_plan(self):
        result = build_deployment_plan({
            "capacity": {"total_cpu_cores": 16, "allocatable_memory_gb": 64},
            "destination": "own_cloud",
            "service_model": "iaas",
            "vm_count": 4,
            "vcpu_per_vm": 2,
            "memory_gb_per_vm": 8,
        })
        self.assertTrue(result["capacity_fit"])
        self.assertEqual(result["execution_status"], "plan_only")
        self.assertIn("No VM", result["notice"])

    def test_plan_detects_insufficient_capacity(self):
        result = build_deployment_plan({
            "capacity": {"total_cpu_cores": 4, "allocatable_memory_gb": 8},
            "destination": "gamgee",
            "service_model": "paas",
            "vm_count": 4,
            "vcpu_per_vm": 2,
            "memory_gb_per_vm": 8,
        })
        self.assertFalse(result["capacity_fit"])

    def test_scaling_recommendation_is_non_mutating(self):
        result = recommend_scaling({"cpu_percent": 90, "memory_percent": 45})
        self.assertEqual(result["recommendation"], "scale_up")

    def test_llm_accepts_only_bounded_sizing_and_safe_cloud_fields(self):
        result = ModelGateway._validate({
            "vm_count": 3,
            "vcpu_per_vm": 8,
            "memory_gb_per_vm": 32,
            "disk_gb_per_vm": 200,
            "high_availability": True,
            "container_image": "ghcr.io/example/api:v1",
            "container_port": 8080,
            "name": "api-service",
            "namespace": "production",
            "admin_command": "reboot",
            "vcpu_per_vm_bad": 999999,
        })
        self.assertEqual(result["vcpu_per_vm"], 8)
        self.assertEqual(result["memory_gb_per_vm"], 32)
        self.assertEqual(result["high_availability"], True)
        self.assertNotIn("admin_command", result)

    def test_llm_output_is_strictly_validated(self):
        result = ModelGateway._validate({
            "vm_count": 3,
            "destination": "gamgee",
            "service_model": "paas",
            "shell_command": "rm -rf /",
        })
        self.assertEqual(result, {
            "vm_count": 3,
            "destination": "gamgee",
            "service_model": "paas",
        })


if __name__ == "__main__":
    unittest.main()
