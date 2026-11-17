# Changelog

All notable changes to The Carpenter are documented here.

## 0.2.0 — 2026-11-17

### Distributed Native Python FaaS
- Added a persistent SQLite function registry and job queue.
- Added version-matched worker capability advertisements.
- Added outbound worker polling, targeted worker jobs, leases and lease tokens.
- Added lease recovery, exponential retry/backoff, max-attempt handling and dead-letter status.
- Added idempotency keys and structured operation events.
- Added worker-side allow-listed discovery and metrics functions.
- Added worker-side Proxmox, Kubernetes and GAMGEE deployment functions.
- Provider credentials are kept on the selected data-plane workers and are not passed through the control plane.
- Approved deployment execution dispatches versioned FaaS jobs and reconciles deployment status from worker results.
- Added one-VM-per-job Proxmox dispatch and a separate worker heartbeat thread for long-running operations.

### Infrastructure Discovery
- Added CPU, memory, disk, OS, architecture and IP inventory.
- Added hypervisor presence checks for KVM, libvirt and Proxmox.
- Added storage mount, network interface and counter inspection.
- Added explicit private-IP TCP reachability probes on allow-listed ports.
- Added fleet discovery jobs pinned to each online node.
- Added heartbeat freshness and stale node exclusion.

### Intelligent Resource Engine
- Added conservative best-fit placement using per-host CPU, RAM and disk.
- Added resource headroom defaults: 15% CPU, 20% memory and 15% disk.
- Added failure-domain-aware placement and HA readiness checks.
- Added basic linear capacity forecasting from supplied time-series samples.

### Dual Cloud Deployment
- Added saved deployment plans, approval and execution lifecycle.
- Added Proxmox VE template-clone, CPU/RAM configuration and VM start adapter.
- Added Kubernetes server-side apply adapter for generated Deployments and ClusterIP Services.
- Added signed HTTPS GAMGEE installer handoff contract.
- Added pre-execution capacity/placement revalidation.

### Autonomous Operations
- Added targeted fleet metrics collection.
- Added threshold and min/max-bounded scaling recommendations.
- Added failover placement plans.
- Added validated HAProxy backend configuration planning.
- Added operation audit events.

### Prompt and integration
- Connected the prompt workflow to queue targeted discovery for newly online nodes.
- Connected user intent to saved deployment plans through the dual-cloud deployment engine.
- Expanded constrained LLM extraction for VM sizing, HA, container image, port and workload names.
- Added deterministic VM-count and sizing parsing when no model is configured.
- Preserved detailed hypervisor/storage/network discovery results across routine heartbeats.
- Added a forward SQLite schema migration for node-targeted jobs.
- Revalidated capacity and placement immediately before approved deployment execution.

### Documentation and engineering
- Rewrote README with installation, worker enrolment, adapter configuration and API examples.
- Added architecture, FaaS, discovery, resource, deployment, operations and security guides.
- Added unit tests for queue leases, retries, idempotency, targeted workers, discovery persistence,
  placement, HA, adapter safety and prompt intent parsing.
- Expanded GitHub Actions to compile Python modules, import-check the API/worker, and run tests.
- Latest CI run: 23 unit tests passed; Python compilation and control-plane/worker imports passed.

### Known limitations
- SQLite is for a single control-plane instance; shared multi-replica queue storage is not yet implemented.
- Worker credentials are shared development tokens; production per-node identity and mTLS are required.
- Worker function versions are matched, but package signatures/digest verification are not implemented.
- GAMGEE requires a compatible external installer endpoint.
- Own-cloud IaaS currently targets Proxmox VE and a prepared cloud-init template.
- Own-cloud PaaS currently targets an existing Kubernetes cluster.
- GAMGEE installer worker requires a terminal synchronous `succeeded`/`completed` response; async status polling is not implemented.
- Closed-loop autoscaling, failover, load-balancer reload, fencing and rollback are not yet enabled.
