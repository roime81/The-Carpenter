from __future__ import annotations

import unittest
from unittest.mock import patch

from app import canvas_runtime


class LiveCanvasRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.session_id = "session-a"
        self.deployment_id = "deployment-a"
        self.plan = {
            "deployment_id": self.deployment_id,
            "requested": {
                "destination": "own_cloud",
                "service_model": "iaas",
                "vm_count": 1,
                "vcpu_per_vm": 2,
                "memory_gb_per_vm": 4,
                "disk_gb_per_vm": 40,
                "high_availability": False,
                "name": "demo-app",
                "namespace": "default",
            },
            "host_count": 1,
            "capacity_ready": True,
            "ha_ready": True,
            "adapter_ready": True,
            "ready_to_execute_after_approval": True,
            "execution_workers": {"proxmox": ["worker-1"]},
            "iac_validation": {"valid": True},
            "iac_bundle": {
                "fingerprint": "f" * 64,
                "resources": [{
                    "resource_id": "vm-demo-01",
                    "name": "demo-app-01",
                    "provider": "proxmox",
                    "kind": "virtual_machine",
                    "worker_id": "worker-1",
                    "spec": {},
                }],
            },
        }
        canvas_runtime.attach_canvas_artifacts(self.plan, "Build one demo VM on my own cloud.")
        self.deployment = {
            "deployment_id": self.deployment_id,
            "status": "executing",
            "updated_at": "2026-11-18T10:03:00+00:00",
            "plan": self.plan,
            "jobs": [{
                "job_id": "provider-job-1",
                "component": "proxmox:worker-1:demo-app-01",
                "function_name": "compute.proxmox_deploy",
                "function_version": "1.0.0",
                "status": "running",
                "attempt": 1,
                "max_attempts": 3,
                "worker_id": "worker-1",
                "result": None,
                "error": None,
            }],
        }
        self.jobs = [
            {
                "job_id": "discovery-job-1",
                "function_name": "discovery.host_inventory",
                "function_version": "1.0.0",
                "status": "succeeded",
                "attempt": 1,
                "max_attempts": 3,
                "worker_id": "worker-1",
                "target_worker_id": "worker-1",
                "created_at": "2026-11-18T10:00:00+00:00",
                "updated_at": "2026-11-18T10:01:00+00:00",
                "payload": {"session_id": self.session_id, "canvas_stage": "discovery"},
                "error": None,
            },
            {
                "job_id": "provider-job-1",
                "function_name": "compute.proxmox_deploy",
                "function_version": "1.0.0",
                "status": "running",
                "attempt": 1,
                "max_attempts": 3,
                "worker_id": "worker-1",
                "target_worker_id": "worker-1",
                "created_at": "2026-11-18T10:02:00+00:00",
                "updated_at": "2026-11-18T10:03:00+00:00",
                "payload": {
                    "deployment_id": self.deployment_id,
                    "iac_resource": {"resource_id": "vm-demo-01"},
                },
                "error": None,
            },
        ]
        self.events = [
            {
                "event_id": "event-1",
                "event_type": "faas.job.succeeded",
                "subject_id": "discovery-job-1",
                "detail": {"worker_id": "worker-1", "function_name": "discovery.host_inventory", "session_id": self.session_id},
                "created_at": "2026-11-18T10:01:00+00:00",
            },
            {
                "event_id": "event-2",
                "event_type": "faas.job.claimed",
                "subject_id": "provider-job-1",
                "detail": {"worker_id": "worker-1", "function_name": "compute.proxmox_deploy", "deployment_id": self.deployment_id},
                "created_at": "2026-11-18T10:02:30+00:00",
            },
            {
                "event_id": "event-3",
                "event_type": "deployment.status.executing",
                "subject_id": self.deployment_id,
                "detail": {"status": "executing"},
                "created_at": "2026-11-18T10:02:00+00:00",
            },
            {
                "event_id": "private-event",
                "event_type": "faas.job.failed",
                "subject_id": "another-session-job",
                "detail": {"session_id": "another-session", "error": "must not leak"},
                "created_at": "2026-11-18T10:02:45+00:00",
            },
        ]

    def _patched_store(self):
        return (
            patch.object(canvas_runtime.store, "list_messages", return_value=[
                {"role": "user", "content": "Build one demo VM", "created_at": "2026-11-18T09:59:00+00:00"},
                {"role": "assistant", "content": "Plan saved", "created_at": "2026-11-18T10:00:00+00:00"},
            ]),
            patch.object(canvas_runtime.store, "get_state", return_value={"deployment_id": self.deployment_id}),
            patch.object(canvas_runtime.store, "list_jobs", return_value=self.jobs),
            patch.object(canvas_runtime.store, "list_events", return_value=self.events),
            patch.object(canvas_runtime.store, "get_agent", return_value={
                "node_id": "worker-1", "hostname": "pve-worker-01", "online": True,
                "last_seen": "2026-11-18T10:03:00+00:00",
                "capabilities": {"compute.proxmox_deploy": "1.0.0"},
            }),
            patch.object(canvas_runtime, "reconcile_status", return_value=self.deployment),
        )

    def test_artifacts_are_persisted_in_the_deployment_plan(self):
        artifacts = self.plan["canvas_artifacts"]
        self.assertIn("Infrastructure Workbook", artifacts["blueprint"]["content"])
        self.assertIn("demo-app", artifacts["blueprint"]["content"])
        self.assertIn("Execution Playbook", artifacts["playbook"]["title"])
        self.assertEqual(artifacts["blueprint"]["filename"], "infrastructure-workbook.md")
        self.assertEqual(artifacts["playbook"]["filename"], "execution-playbook.md")

    def test_snapshot_projects_real_jobs_resources_and_worker_events(self):
        patches = self._patched_store()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = canvas_runtime.build_canvas_snapshot(self.session_id)

        nodes = {node["id"]: node for node in result["nodes"]}
        self.assertEqual(nodes["stage:discovery"]["status"], "succeeded")
        self.assertEqual(nodes["stage:provision"]["status"], "running")
        self.assertEqual(nodes["job:provider-job-1"]["status"], "running")
        self.assertEqual(nodes["worker:worker-1"]["label"], "pve-worker-01")
        self.assertTrue(nodes["worker:worker-1"]["logs"])
        self.assertEqual(nodes["resource:vm-demo-01"]["status"], "running")
        self.assertIn({"kind": "blueprint", "title": "Infrastructure Workbook",
                       "filename": "infrastructure-workbook.md",
                       "generated_at": self.plan["canvas_artifacts"]["blueprint"]["generated_at"]},
                      result["artifacts"])
        self.assertNotIn("private-event", {event["event_id"] for event in result["events"]})

    def test_playbook_preview_reflects_live_execution_status(self):
        patches = self._patched_store()
        with patches[1], patches[5]:
            artifact = canvas_runtime.get_canvas_artifact(self.session_id, "playbook")
        steps = {step["id"]: step for step in artifact["steps"]}
        self.assertEqual(steps["approve"]["status"], "succeeded")
        self.assertEqual(steps["dispatch"]["status"], "running")
        self.assertEqual(steps["verify"]["status"], "waiting")
        self.assertIn("RUNNING", artifact["content"])

    def test_artifact_lookup_rejects_unknown_kind(self):
        with patch.object(canvas_runtime.store, "get_state", return_value={"deployment_id": self.deployment_id}):
            self.assertIsNone(canvas_runtime.get_canvas_artifact(self.session_id, "secrets"))


if __name__ == "__main__":
    unittest.main()
