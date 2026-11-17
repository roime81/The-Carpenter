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

    def test_admin_can_take_over_an_operator_plan_by_explicit_id(self):
        deployment_id = "3d8f5b70-a37f-4c21-8f48-0c2b7d9e0012"
        approved = {
            "deployment_id": deployment_id,
            "plan": {"iac_bundle": {"fingerprint": "c" * 64}},
        }
        execution = {
            "status": "queued",
            "iac_fingerprint": "c" * 64,
            "jobs": [{
                "component": "api-vm",
                "function_name": "compute.proxmox_deploy",
                "target_worker_id": "pve-01",
            }],
        }
        with patch.object(main.store, "get_state", return_value={}), \
             patch.object(main, "_approve_saved_plan", return_value=approved) as approve, \
             patch.object(main, "_execute_approved_plan", return_value=execution) as execute, \
             patch.object(main.store, "record_event"), \
             patch.object(main.store, "set_state") as set_state:
            answer = main._handle_chat_deployment_command(
                "admin-session",
                {"subject": "web-admin", "role": "admin"},
                f"approve and deploy {deployment_id}",
            )
        approve.assert_called_once_with(deployment_id, "web-admin", "web-chat")
        execute.assert_called_once_with(deployment_id, "web-admin", "web-chat")
        set_state.assert_called_once()
        self.assertIn(deployment_id, answer)

    def test_explicit_deployment_status_supports_handoff(self):
        deployment_id = "3d8f5b70-a37f-4c21-8f48-0c2b7d9e0012"
        record = {
            "status": "approved",
            "destination": "own_cloud",
            "service_model": "iaas",
            "approved_by": "web-admin",
            "jobs": [],
        }
        with patch.object(main.store, "get_state", return_value={}), \
             patch.object(main, "reconcile_deployment_status", return_value=record) as reconcile, \
             patch.object(main.store, "set_state") as set_state:
            answer = main._handle_chat_deployment_command(
                "viewer-session",
                {"subject": "web-operator", "role": "operator"},
                f"status {deployment_id}",
            )
        reconcile.assert_called_once_with(deployment_id)
        set_state.assert_called_once()
        self.assertIn("Deployment status: approved", answer)
        self.assertIn(deployment_id, answer)


if __name__ == "__main__":
    unittest.main()
