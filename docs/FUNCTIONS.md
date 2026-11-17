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

The worker only executes a function if it has that exact function name/version installed. Worker capability advertisements are refreshed in the node heartbeat.

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

The delivery model is at-least-once. A worker can crash after doing work but before reporting success, so future mutating functions must use operation IDs/idempotency keys and compensating actions. Queue idempotency keys are currently stored in SQLite.

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

To force work onto a specific enrolled node, pass `target_worker_id`. This is used by fleet-wide discovery/metrics jobs to ensure every online node is examined.

## Runtime limitations

- The queue is durable in SQLite but the control plane remains a single-instance MVP.
- Worker handlers are shipped with the node agent; there is no remote code download or package execution.
- Function digests are registry metadata, not yet signed artifact verification.
- Leases and retries provide at-least-once delivery, not exactly-once effects.
- Mutating provider functions need stronger per-operation idempotency, compensation and approval metadata before production.
- Current jobs run synchronously in the worker process. A hung handler can outlive a caller wait; production workers need process/container isolation and cancellation.
