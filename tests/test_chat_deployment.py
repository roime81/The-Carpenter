import unittest
from unittest.mock import patch

from app import main


class ConversationalDeploymentCommandTests(unittest.TestCase):
    def test_unknown_text_is_left_for_the_agent_orchestrator(self):
        self.assertIsNone(main._handle_chat_deployment_command(
            "session-1", {"subject": "web-admin", "role": "admin"},
            "Please make my app more resilient",
        ))

    def test_operator_cannot_approve_or_execute(self):
        with patch.object(main.store, "get_state", return_value={"deployment_id": "deployment-1"}), \
             patch.object(main.store, "record_event") as record_event:
            answer = main._handle_chat_deployment_command(
                "session-1", {"subject": "web-operator", "role": "operator"}, "approve and deploy"
            )
        self.assertIn("requires the **admin** role", answer)
        record_event.assert_called_once_with(
            "deployment.chat.command.denied", "deployment-1",
            {"actor": "web-operator", "role": "operator", "action": "approve_deploy"},
        )

    def test_admin_can_approve_and_deploy_the_saved_chat_plan(self):
        approved = {
            "deployment_id": "deployment-1",
            "plan": {"iac_bundle": {"fingerprint": "a" * 64}},
        }
        execution = {
            "status": "queued",
            "iac_fingerprint": "a" * 64,
            "jobs": [{
                "component": "vm-app-01",
                "function_name": "compute.proxmox_deploy",
                "target_worker_id": "pve-worker-01",
            }],
        }
        with patch.object(main.store, "get_state", return_value={"deployment_id": "deployment-1"}), \
             patch.object(main, "_approve_saved_plan", return_value=approved) as approve, \
             patch.object(main, "_execute_approved_plan", return_value=execution) as execute, \
             patch.object(main.store, "record_event"), \
             patch.object(main.store, "set_state") as set_state:
            answer = main._handle_chat_deployment_command(
                "session-1", {"subject": "web-admin", "role": "admin"}, "approve and deploy"
            )
        approve.assert_called_once_with("deployment-1", "web-admin", "web-chat")
        execute.assert_called_once_with("deployment-1", "web-admin", "web-chat")
        self.assertIn("queued the provider work", answer)
        self.assertIn("compute.proxmox_deploy", answer)
        set_state.assert_called_once()

    def test_approval_alone_does_not_dispatch_resources(self):
        approved = {
            "plan": {"iac_bundle": {"fingerprint": "b" * 64}},
        }
        with patch.object(main.store, "get_state", return_value={"deployment_id": "deployment-2"}), \
             patch.object(main, "_approve_saved_plan", return_value=approved), \
             patch.object(main, "_execute_approved_plan") as execute, \
             patch.object(main.store, "record_event"):
            answer = main._handle_chat_deployment_command(
                "session-2", {"subject": "web-admin", "role": "admin"}, "approve"
            )
        self.assertIn("No resources have been changed", answer)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
