# Native Python FaaS

## Function model

All infrastructure capabilities are represented as versioned Python functions. The model selects intent; a typed planner chooses registered functions; workers execute only built-in or explicitly installed handlers. No generated shell or Python code is run.

## Distributed worker functions

| Function | Version | Behaviour | Side effects |
|---|---:|---|---|
| `discovery.host_inventory` | 1.0.0 | CPU, RAM, OS, disk, hostname facts | Read-only |
| `discovery.hypervisor_probe` | 1.0.0 | KVM, libvirt, Proxmox, container and Kubernetes tool presence | Read-only |
| `discovery.storage_network` | 1.0.0 | Mounted filesystems, interfaces, link state, counters | Read-only |
| `operations.metrics_snapshot` | 1.0.0 | CPU, memory, root-disk and network snapshot | Read-only |
| `network.tcp_probe` | 1.0.0 | Explicit private IP and allow-listed TCP ports | Read-only |
| `compute.proxmox_deploy` | 1.0.0 | Clone, size and start one VM from a prepared template | Mutating; approved plan only |
| `platform.kubernetes_deploy` | 1.0.0 | Server-side apply Deployment and ClusterIP Service | Mutating; approved plan only |
| `gamgee.bootstrap` | 1.0.0 | Signed GAMGEE bootstrap/expand request | Mutating; approved plan only |

Provider functions are advertised only when the worker has the relevant local endpoint and credentials configured. See [DEPLOYMENT.md](DEPLOYMENT.md). The worker only executes a function if it has that exact function name/version installed. A job contains function name, version and JSON payload; it never contains executable code.

## Local control-plane functions

- `assessment.capacity`: preliminary aggregate capacity estimate.
- `planning.deployment`: simple non-mutating VM sizing estimate.
- `operations.scaling_recommendation`: non-mutating scale recommendation.

## Queue lifecycle

1. The control plane validates that a function/version is registered.
2. It writes a durable queued job with a unique ID, JSON payload and retry policy.
3. A worker polls the claim endpoint over its outbound connection.
4. The scheduler checks its advertised function versions and optional target-worker constraint.
5. The scheduler sets a lease token and expiry and increments the attempt counter.
6. The worker runs its allow-listed handler and reports a result or failure.
7. Expired/failed jobs are retried with exponential backoff; exhausted jobs become `dead`.

The delivery model is at-least-once. A worker can crash after doing work but before reporting success. Provider handlers must therefore use stable operation IDs, deterministic resource names, reconciliation before creation and idempotency keys. Proxmox uses deterministic VM names to recover a partially completed VM; Kubernetes uses server-side apply; the GAMGEE installer must enforce idempotency by Carpenter deployment ID.

## Deployment FaaS lifecycle

1. The control plane persists a plan.
2. A human approves that saved plan.
3. The control plane revalidates capacity and execution-worker capability.
4. It queues one Proxmox job per VM, one Kubernetes job per PaaS component, or one GAMGEE installer job.
5. The control plane links all jobs to the deployment record.
6. The deployment status becomes `succeeded` only after every linked job succeeds. Any dead-lettered job makes the deployment `failed`; partial provider success is shown through the linked job results.

The `POST /api/v1/deployments/{id}/execute` response means **queued**, not provisioned. Read `GET /api/v1/deployments/{id}` for terminal status.

## API

Admin calls require `X-Carpenter-Token`; workers require `X-Agent-Token`.

- `GET /api/v1/functions`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/workers/{worker_id}/claim`
- `POST /api/v1/workers/{worker_id}/jobs/{job_id}/complete`
- `POST /api/v1/workers/{worker_id}/jobs/{job_id}/fail`

Example enqueue:

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"function_name":"discovery.hypervisor_probe","function_version":"1.0.0","payload":{},"max_attempts":3}'
```

To force work onto a specific enrolled node, pass `target_worker_id`. This is used by fleet-wide discovery/metrics jobs and deployment jobs to ensure the intended data-plane worker executes the function.

## Runtime limitations

- The queue is durable in SQLite but the control plane remains a single-instance MVP.
- Worker handlers are shipped with the node agent; there is no remote code download or package execution.
- Function digests are registry metadata, not yet signed artifact verification.
- Leases and retries provide at-least-once delivery, not exactly-once effects.
- Proxmox operations create VMs from prepared cloud-init templates; they do not yet provision arbitrary network/storage profiles or resize template disks.
- Kubernetes operations target an existing cluster; they do not bootstrap a cluster on bare metal.
- GAMGEE requires an external installer implementing the signed request contract and terminal response.
- Production workers need process/container isolation, resource quotas, package signatures, per-node identity and secret-manager integration.
