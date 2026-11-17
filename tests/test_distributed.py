from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app import store


class DistributedQueueTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.previous_settings = store.settings
        store.settings = SimpleNamespace(
            database_path=str(Path(self.tempdir.name) / "carpenter.db"),
            agent_stale_seconds=120,
        )
        store.initialise_store()
        store.register_function(
            "discovery.host_inventory", "1.0.0",
            "Read-only inventory", "test-digest-v1",
        )
        store.upsert_agent({
            "node_id": "worker-node-0001",
            "hostname": "worker-01",
            "capabilities": {"discovery.host_inventory": "1.0.0"},
        })

    def tearDown(self):
        store.settings = self.previous_settings
        self.tempdir.cleanup()

    def test_worker_claims_and_completes_leased_job(self):
        queued = store.enqueue_job(
            "discovery.host_inventory", "1.0.0", {"scope": "self"},
            idempotency_key="inventory-once",
        )
        claimed = store.claim_job("worker-node-0001", lease_seconds=30)
        self.assertEqual(claimed["job_id"], queued["job_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempt"], 1)

        self.assertFalse(store.complete_job(
            queued["job_id"], "worker-node-0001", "wrong-lease", {"ok": True}
        ))
        self.assertTrue(store.complete_job(
            queued["job_id"], "worker-node-0001", claimed["lease_token"], {"hostname": "worker-01"}
        ))
        completed = store.get_job(queued["job_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"]["hostname"], "worker-01")

    def test_idempotency_returns_same_job(self):
        first = store.enqueue_job(
            "discovery.host_inventory", "1.0.0", {},
            idempotency_key="stable-request",
        )
        second = store.enqueue_job(
            "discovery.host_inventory", "1.0.0", {"different": "payload"},
            idempotency_key="stable-request",
        )
        self.assertEqual(first["job_id"], second["job_id"])

    def test_failed_job_is_retried_then_dead_lettered(self):
        queued = store.enqueue_job(
            "discovery.host_inventory", "1.0.0", {}, max_attempts=2
        )
        first = store.claim_job("worker-node-0001", lease_seconds=30)
        self.assertTrue(store.fail_job(
            queued["job_id"], "worker-node-0001", first["lease_token"], "temporary error"
        ))
        with store._connect() as connection:
            connection.execute(
                "UPDATE faas_jobs SET available_at=? WHERE job_id=?",
                (store.iso_now(), queued["job_id"]),
            )
        second = store.claim_job("worker-node-0001", lease_seconds=30)
        self.assertEqual(second["attempt"], 2)
        self.assertTrue(store.fail_job(
            queued["job_id"], "worker-node-0001", second["lease_token"], "still failing"
        ))
        self.assertEqual(store.get_job(queued["job_id"])["status"], "dead")


if __name__ == "__main__":
    unittest.main()
