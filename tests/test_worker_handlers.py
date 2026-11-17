from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from handlers import execute, installed_capabilities


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


if __name__ == "__main__":
    unittest.main()
