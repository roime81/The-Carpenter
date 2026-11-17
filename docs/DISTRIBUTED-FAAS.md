# Distributed Native Python FaaS Engine

## Overview

The Carpenter control plane stores jobs and a versioned function catalogue. Node agents are also Python workers. Workers maintain an outbound heartbeat, advertise installed function versions, poll for jobs, execute only local allow-listed handlers and report structured outcomes.

The control plane does not download or execute model-generated code.

## Worker enrolment

On every target server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r node_agent/requirements.txt

export CARPENTER_URL="https://carpenter.example.com"
export CARPENTER_AGENT_TOKEN="the-node-enrolment-token"
export CARPENTER_FAILURE_DOMAIN="rack-a"
python node_agent/agent.py
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r node_agent/requirements.txt
$env:CARPENTER_URL = "https://carpenter.example.com"
$env:CARPENTER_AGENT_TOKEN = "the-node-enrolment-token"
$env:CARPENTER_FAILURE_DOMAIN = "rack-a"
python node_agent/agent.py
```

The worker sends a heartbeat every 30 seconds by default and polls for jobs every 2 seconds. Environment variables:
- `CARPENTER_NODE_ID`: optional stable node ID override.
- `CARPENTER_FAILURE_DOMAIN`: rack, zone, cluster, site or other independently verified failure domain.
- `CARPENTER_HEARTBEAT_SECONDS`: heartbeat interval, minimum 15.
- `CARPENTER_WORKER_POLL_SECONDS`: queue poll interval, minimum 1.
- `LOG_LEVEL`: Python log level.

Run the process under a dedicated service account and supervisor (systemd, Windows Service wrapper or an approved service manager). Discovery functions do not need root. Provider credentials are optional and belong only on the worker authorised to execute that provider; use a secret manager or protected service environment in production.

## Function registration and versions

The control plane registers function name/version pairs. Workers advertise a dictionary of supported versions. A worker may claim a job only when:
- Its heartbeat is fresh.
- It advertises the exact function name and version.
- The job has no worker target or targets that worker ID.

The worker ships allow-listed Python code for discovery, metrics and provider execution. Provider capabilities are advertised only when that worker has the corresponding local environment configuration:

| Function | Required worker-side configuration |
|---|---|
| `compute.proxmox_deploy@1.0.0` | Proxmox HTTPS URL, API token ID/secret, node name and prepared template VMID |
| `platform.kubernetes_deploy@1.0.0` | Kubernetes HTTPS API URL and namespace-scoped service-account token |
| `gamgee.bootstrap@1.0.0` | GAMGEE HTTPS installer URL and HMAC signing secret |

Function code is shipped with the agent package; a job contains only the function name, version and JSON payload. No code package or script is sent by the model/control plane.

## Queue semantics

Job state:
- `queued`: ready at `available_at`.
- `running`: leased to one worker until `lease_until`.
- `succeeded`: accepted result stored.
- `dead`: attempt budget exhausted or worker lease repeatedly expired.

A failed attempt is retried with exponential backoff capped at five minutes. An expired lease is returned to the queue if attempts remain. Job completion/failure is accepted only from the worker with the matching lease token before lease expiry.

**Delivery is at-least-once.** A worker can perform a side effect and crash before acknowledging it. Mutating functions must use an operation ID/idempotency key, verify current state before mutation, and provide compensation/rollback.

## Provider deployment jobs

Approved cloud deployments are also native distributed functions:
- `compute.proxmox_deploy@1.0.0`: one VM per job, targeted to a configured Proxmox worker. Stable VM names allow retries to reconcile an existing VM.
- `platform.kubernetes_deploy@1.0.0`: server-side applies a generated Deployment and ClusterIP Service to an existing Kubernetes cluster.
- `gamgee.bootstrap@1.0.0`: sends a signed bootstrap/expand request to a configured GAMGEE installer. The installer must return a terminal completed/succeeded result; an asynchronous accepted response is not reported as completed.

The control plane creates a deployment record, obtains explicit approval, rechecks live placement/capabilities and enqueues these functions. The deployment remains executing until every linked job succeeds or one reaches the dead-letter state. Provider credentials are not held by the web/API process.

## Targeted fleet jobs

The control plane targets each discovery/metrics invocation to a node ID. A generic FaaS job can specify `target_worker_id` when required. This ensures that a fleet scan creates one job per function per online worker, not a handful of jobs that all happen to run on one worker.

## Enqueue and inspect a job

Set the admin token:

```bash
export CARPENTER_ADMIN_TOKEN="your-admin-token"
```

Enqueue an inventory job on any compatible worker:

```bash
curl -X POST https://carpenter.example.com/api/v1/jobs \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"function_name":"discovery.host_inventory","function_version":"1.0.0","payload":{},"max_attempts":3}'
```

Fleet discovery:

```bash
curl -X POST https://carpenter.example.com/api/v1/discovery/scan \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

Inspect jobs:

```bash
curl https://carpenter.example.com/api/v1/jobs \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

## Scaling the FaaS system

The current queue uses SQLite WAL and is intended for one control-plane instance. For distributed control-plane replicas, move jobs, leases, worker registry, approvals and audit data to PostgreSQL or another transactional store with atomic row claiming. Then add independent worker pools, concurrency limits, rate limits, dead-letter operations, package signing and workload isolation.

Do not run multiple Carpenter API replicas against separate local SQLite files and assume they share a queue.
