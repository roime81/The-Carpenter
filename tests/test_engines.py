from __future__ import annotations

import unittest

from app.resource_engine import plan_placement, forecast_capacity
from app.operations_engine import assess_high_availability, recommend_action, render_haproxy_backends
from app.adapters.proxmox import ProxmoxAdapter
from app.adapters.kubernetes import KubernetesAdapter


def host(node_id: str, domain: str) -> dict:
    return {
        "node_id": node_id,
        "hostname": node_id,
        "failure_domain": domain,
        "cpu_cores": 16,
        "memory_total_bytes": 128 * 1024**3,
        "memory_available_bytes": 112 * 1024**3,
        "disk_free_bytes": 1000 * 1024**3,
        "online": True,
        "discovery": {"hypervisor": {"kvm_device": True}},
    }


class ResourceAndOperationsTests(unittest.TestCase):
    def test_best_fit_placement_spreads_ha_across_domains(self):
        result = plan_placement(
            [host("node-a", "rack-a"), host("node-b", "rack-b")],
            vm_count=4, vcpu_per_vm=2, memory_gb_per_vm=8,
            disk_gb_per_vm=50, high_availability=True,
        )
        self.assertTrue(result["feasible"])
        self.assertEqual(result["placed_vm_count"], 4)
        self.assertEqual(len(result["failure_domains_used"]), 2)

    def test_placement_refuses_unverified_hypervisor(self):
        item = host("node-c", "rack-c")
        item["discovery"] = {"hypervisor": {"kvm_device": False}}
        result = plan_placement([item], vm_count=1)
        self.assertFalse(result["feasible"])
        self.assertEqual(result["placed_vm_count"], 0)

    def test_capacity_forecast_requires_three_samples(self):
        result = forecast_capacity([
            {"days_from_now": 0, "utilisation_percent": 50},
            {"days_from_now": 10, "utilisation_percent": 60},
            {"days_from_now": 20, "utilisation_percent": 70},
        ])
        self.assertTrue(result["forecast_available"])
        self.assertAlmostEqual(result["daily_growth_percent"], 1.0, places=2)

    def test_ha_requires_more_than_one_failure_domain(self):
        result = assess_high_availability([host("node-a", "same"), host("node-b", "same")])
        self.assertFalse(result["ha_ready"])

    def test_scale_recommendation_never_claims_execution(self):
        result = recommend_action(
            {"cpu_percent": 92, "memory_percent": 45},
            {"min_replicas": 2, "current_replicas": 3, "max_replicas": 5},
        )
        self.assertEqual(result["action"], "scale_out")
        self.assertEqual(result["proposed_replicas"], 4)
        self.assertEqual(result["execution_status"], "recommendation_only")

    def test_haproxy_config_rejects_invalid_backend(self):
        with self.assertRaises(ValueError):
            render_haproxy_backends([{"address": "bad; inject", "port": 80}])

    def test_adapters_require_tls(self):
        with self.assertRaises(ValueError):
            ProxmoxAdapter("http://proxmox.local", "root@pam!api", "secret")
        with self.assertRaises(ValueError):
            KubernetesAdapter("http://kubernetes.local", "token")


if __name__ == "__main__":
    unittest.main()
