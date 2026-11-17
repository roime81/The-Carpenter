import unittest

from app.orchestrator import CarpenterOrchestrator


class PromptIntentFallbackTests(unittest.TestCase):
    def test_vm_count_parser_ignores_earlier_resource_numbers(self):
        self.assertEqual(
            CarpenterOrchestrator._number_from_prompt("4 vCPU and 16 GB RAM for 3 VMs"),
            3,
        )

    def test_bare_number_only_accepted_when_asking_for_vm_count(self):
        self.assertIsNone(CarpenterOrchestrator._number_from_prompt("4 vCPU"))
        self.assertEqual(
            CarpenterOrchestrator._number_from_prompt("4", allow_first_number=True),
            4,
        )

    def test_deterministic_sizing_extracts_only_explicit_fields(self):
        result = CarpenterOrchestrator._deterministic_sizing(
            "Create 4 VMs, each with 8 vCPU, 32 GB RAM, 200 GB disk, port 8080"
        )
        self.assertEqual(result, {
            "vcpu_per_vm": 8,
            "memory_gb_per_vm": 32,
            "disk_gb_per_vm": 200,
            "container_port": 8080,
        })

    def test_deterministic_sizing_ignores_out_of_range_values(self):
        result = CarpenterOrchestrator._deterministic_sizing(
            "999999 vCPU and 999999 GB RAM"
        )
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
