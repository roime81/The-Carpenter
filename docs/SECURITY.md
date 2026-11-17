# Security Model

## Current safety boundary

The prompt and planning APIs do not grant the model arbitrary execution access. The current node agent runs only a fixed allow-list of Python handlers shipped in the repository. It does not accept shell commands, dynamically import model-generated code, or execute arbitrary scripts from the control plane.

Discovery and metrics are read-only. The TCP probe accepts explicit private, loopback or link-local IP literals and a restricted port allow-list; it does not perform CIDR sweeps or public address scanning.

Deployment mutations are behind plan → approval → execute routes. The adapters require explicit configuration:
- Proxmox: HTTPS API token and a prebuilt cloud-init template.
- Kubernetes: HTTPS API and a service account scoped to the intended namespace/resources.
- GAMGEE: HTTPS installer endpoint and a shared HMAC signing secret following the Carpenter request contract.

## Development credentials

The sample deployment uses:
- `CARPENTER_ADMIN_TOKEN` for administrative APIs.
- `CARPENTER_AGENT_ENROLLMENT_TOKEN` for node heartbeat and worker calls.

Keep them distinct. These are still shared development secrets, not a production node identity system. Anyone holding the worker token can impersonate an enrolled worker. Use TLS at all times and never expose the development service directly to the public internet.

The prompt UI currently does not provide production authentication/SSO or multi-tenant authorization. The current session cookie is not a complete identity or CSRF defense.

## Mandatory production controls

1. TLS everywhere; reject cleartext worker and provider connections.
2. Unique node identity and short-lived per-node enrollment credentials.
3. mTLS or signed workload identity and node revocation.
4. SSO, RBAC, tenant isolation and CSRF protection for browser actions.
5. Secrets manager/KMS for all adapter credentials; rotate and audit access.
6. Signed and versioned function artifacts with digest verification by workers.
7. Process/container isolation, resource limits and cancellation for FaaS execution.
8. Persistent, durable queue with controlled retries, leases, dead-letter queues and audit.
9. Explicit approval, policy evaluation and compensation plans for privileged mutations.
10. Append-only audit events, telemetry redaction and alerting.
11. Egress allow-lists, network segmentation and firewall restrictions for workers.
12. Database backups and tested recovery.

## Execution safety

- Never execute arbitrary commands supplied in prompts or model output.
- Never treat ping or TCP reachability as authorization to manage a host.
- Use a typed function catalogue and strict function-specific payload validation.
- Bind jobs to worker identity and the exact supported function version.
- Accept a job result only from the worker holding its active lease token.
- Treat retries as at-least-once and design all mutation handlers for idempotency.
- Require human approval for VM creation, network/storage changes, platform installation, scaling, failover and destructive work.

## Storage and availability

SQLite WAL is used for the current single-instance control plane. It is not a clustered multi-writer database. Before running multiple API replicas, migrate queue, sessions, inventory, approval and audit data to a shared transactional database and add a distributed scheduler/locking model.
