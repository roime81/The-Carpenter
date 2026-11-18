# Changelog

All notable changes to The Carpenter are documented here.

## 0.7.0 — 2026-11-18

**Release notes:** [The Carpenter v0.7.0 — Infrastructure Digital Twin](docs/releases/v0.7.0.md)

### Infrastructure Digital Twin
- Added durable typed resource inventory, relationships and versioned observation history tables to the control-plane store.
- Added stable endpoint-scoped provider/native resource IDs so same-named resources in different Proxmox/Kubernetes environments remain distinct.
- Ingested heartbeat-backed physical hosts, private network interfaces/subnets, mounted storage, hypervisor capabilities and runtime presence.
- Added optional Proxmox cluster inventory discovery for hypervisor nodes, QEMU/LXC guests, storage pools, bridges and attached VM volumes.
- Added optional Kubernetes namespace inventory discovery for controllers, ReplicaSets, Services, ClusterIPs, Pods, pod IPs, PVCs, PVs and pod-scheduled nodes where RBAC permits.
- Projected provider observations and typed relationships into the same live graph as the execution workflow; actual resource status follows worker/provider observations.
- Imported successful provider operation results after FaaS completion, so resources created or changed by The Carpenter appear in the Digital Twin as observed objects.
- Added authenticated `/api/v1/twin/snapshot`, `/api/v1/twin/refresh` and `/api/v1/twin/resources/{resource_id}/history` endpoints.
- Added operator/admin **Refresh topology** control; refresh queues read-only inventory jobs only on eligible online workers.
- Added a distinct Partial discovery state when provider inventory has read warnings; warning counts are visible in the job inspector instead of presenting incomplete scans as complete.
- Added tests for resource identity/version/history, Proxmox resource relationships, Kubernetes workload/network/storage topology and partial-inventory status.
- Documented that the twin is installation-wide in this release, that Kubernetes inventory is namespace/RBAC-scoped, and that AWS/Azure/GCP inventories, deletion inference and automated drift remediation are follow-on work.

## 0.6.0 — 2026-11-18

### Live Infrastructure Network
- Replaced the conceptual linear flowchart presentation with an organic, light-background node mesh inspired by `docs/assets/8805.jpg`, with low-emphasis proximity strands and stronger semantic links.
- Added a session-scoped graph projection built from persisted conversations, deployment plans, IaC resources, FaaS jobs, enrolled workers and operation events.
- Added authenticated Server-Sent Event snapshots backed by the durable SQLite records and refreshed at a 1.5-second cadence.
- Instrumented worker claims, completions and failures with explicit event records, including function/version, worker, attempt, session/deployment scope and timestamps.
- Added one stable graph node per job and participating worker; job/worker inspectors display real status, timestamps, retry attempts and sanitized event history.
- Added resource node status derived from linked provider jobs instead of treating plan-only resources as deployed.
- Generated Infrastructure Workbook and Execution Playbook previews from the saved plan, persisted them in the deployment record and exposed authenticated preview endpoints.
- Added regression coverage for graph projection, session isolation, per-worker history and live playbook state.
- Documented that SSE is a polling-backed projection, not a message-broker push bus; artifact previews are persisted in the deployment plan record rather than as separate filesystem files.

## 0.5.1 — 2026-11-18

### White theme refinement
- Replaced the dark translucent canvas with a clean porcelain-white workspace.
- Updated the graph surface, node labels, dependency edges, legend, inspector, journal and prompt dock for light backgrounds.
- Retained distinct status semantics using restrained teal, blue, amber and red accents.
- Applied the same light theme to the sign-in surface for a consistent launch-to-workspace experience.

## 0.5.0 — 2026-11-18

### Living Infrastructure Canvas
- Replaced the narrow prompt-only home screen with a transparent, visual-first infrastructure workspace.
- Added a graph canvas that begins at the Carpenter launcher and connects intent, discovery, blueprint, playbook, native functions, IaC, approval, provisioning and reconciliation stages.
- Added interactive SVG nodes with keyboard support, dependency edges, status colors, active pulses and node selection.
- Added a contextual node inspector with type, role and dependency information.
- Added an execution journal beside the graph and a persistent prompt dock.
- Added canvas label toggle, fit control, responsive layout and translucent visual treatment (subsequently refined to the white theme in 0.5.1).
- Derived the initial status visualization from saved conversation responses; it does not yet claim live event streaming from workers.
- Documented that Blueprint and Playbook are visual workflow concepts, not persisted workbook/playbook artifacts.

### Known UI follow-ups
- Add authenticated event-stream or polling integration for live worker/job status updates.
- Persist a full per-deployment graph model with node/edge IDs and timestamps.
- Add zoom/pan, graph minimap, artifact previews and per-node logs.

undefined