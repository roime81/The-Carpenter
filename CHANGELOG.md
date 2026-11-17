# Changelog

All notable changes to The Carpenter are documented here.

## 0.3.0 — 2026-11-17

### Product definition: AI Cloud Deployment Agent
- Repositioned The Carpenter as an AI Cloud Deployment Agent and AI Infrastructure-as-Code Agent.
- Defined the goal-driven workflow: understand, discover, design, compile IaC, validate, authorise, provision, reconcile and report.
- Updated the LLM contract so the model extracts bounded intent and does not emit executable YAML, shell or arbitrary provider instructions.

### Internal AI IaC Engine
- Added deterministic `carpenter.iac/v1` compiler for Proxmox, Kubernetes and GAMGEE resource plans.
- Added generated Kubernetes Deployment and ClusterIP Service YAML with workload CPU/memory sizing.
- Added Proxmox VM resource graph and GAMGEE bootstrap plan artifacts.
- Added canonical resource-graph SHA-256 fingerprint and per-artifact SHA-256 hashes.
- Added safe YAML parsing, resource allow-list checks and tamper detection before provider dispatch.
- Added `GET /api/v1/deployments/{id}/iac` to inspect generated resources, YAML and validation metadata.
- Updated Kubernetes worker to apply the exact generated manifests after validating supported resource shapes.
- Updated Proxmox worker to require a generated VM resource and matching IaC fingerprint.

### Agent experience and documentation
- Prompt responses now report generated IaC resources, filenames and the bundle fingerprint.
- Corrected prompt readiness checks to use live worker capability names.
- Added AI Agent and IaC Engine technical guides.
- Updated README, architecture, deployment, functions, security and roadmap documentation.
- Explicitly documented that users do not author YAML for supported providers, while first-time Node Agent installation and worker credential onboarding remain prerequisites in this release.

### Current limitations
- General Terraform/OpenTofu and Ansible generation are not implemented.
- Automatic remote SSH/bootstrap of unenrolled bare-metal hosts is not implemented.
- Proxmox disk resize, custom network/storage profiles and per-VM cloud-init customisation are not yet applied.
- Kubernetes PaaS requires an existing cluster; cluster topology/HA discovery remains future work.
- Authenticated conversational approval requires the future SSO/RBAC integration; the current approval boundary is the admin API.

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
- Added a conservative Kubernetes HA gate: PaaS HA is not reported ready until cluster topology can be inspected.

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
- Latest 0.2.0 CI run: 30 unit tests passed; Python compilation and control-plane/worker imports passed.

### Known limitations
- SQLite is for a single control-plane instance; shared multi-replica queue storage is not yet implemented.
- Worker credentials are shared development tokens; production per-node identity and mTLS are required.
- Worker function versions are matched, but package signatures/digest verification are not implemented.
- GAMGEE requires a compatible external installer endpoint.
- Own-cloud IaaS currently targets Proxmox VE and a prepared cloud-init template.
- Own-cloud PaaS currently targets an existing Kubernetes cluster.
- GAMGEE installer worker requires a terminal synchronous `succeeded`/`completed` response; async status polling is not implemented.
- Closed-loop autoscaling, failover, load-balancer reload, fencing and rollback are not yet enabled.
