# Engineering Roadmap — 2026

This roadmap tracks the five requested engineering programmes. The first implementation increment is committed; several provider capabilities are functional adapters while other integrations remain explicit contracts.

## 1. Distributed Native FaaS Engine — foundation implemented

- [x] Persistent SQLite job queue and function registry.
- [x] Versioned function name + version matching.
- [x] Outbound worker polling and targeted worker assignment.
- [x] Lease tokens, expiry recovery, retry/backoff and dead-letter state.
- [x] Job idempotency keys and event audit.
- [x] Built-in node discovery and metrics functions.
- [x] Dynamic provider capability advertisements from worker-local configuration.
- [x] Provider deployment functions for Proxmox, Kubernetes and GAMGEE.
- [x] One Proxmox VM per FaaS job, worker heartbeat during long-running operations and deployment job reconciliation.
- [ ] Shared PostgreSQL queue and multi-control-plane coordination.
- [ ] Isolated worker processes/containers and cancellation.
- [ ] Signed function packages, signature verification and automated rollback.
- [ ] Tenant quotas, rate limits and worker resource limits.

## 2. Infrastructure Discovery Engine — first capability set implemented

- [x] Fresh-heartbeat online/offline state.
- [x] CPU, RAM, disk, OS, architecture and IP inventory.
- [x] KVM/libvirt/Proxmox/container/Kubernetes presence probes.
- [x] Storage mount and network-interface inventory.
- [x] Explicit private-IP TCP probes on a port allow-list.
- [ ] Hypervisor API inventory and VM/workload enumeration.
- [ ] Kubernetes node readiness, topology zones, control-plane quorum and storage-failure-domain discovery.
- [ ] Storage IOPS/latency and network throughput benchmarks.
- [ ] GPU, NUMA, PCIe, power and failure-domain discovery.
- [ ] Provider connectors and unique per-node identities.

## 3. Intelligent Resource Engine — first planner implemented

- [x] Conservative per-host placement using CPU, RAM and free disk.
- [x] Configurable reserve model (initial defaults: 15% CPU, 20% memory, 15% disk).
- [x] HA-aware spread across declared failure domains.
- [x] Basic linear capacity forecast from supplied time-series samples.
- [ ] Live reservation accounting and scheduler reconciliation.
- [ ] NUMA/GPU/IOPS/network-aware bin packing.
- [ ] Cost and power-aware placement.
- [ ] Predictive models trained from retained telemetry and workload seasonality.

## 4. Dual Cloud Deployment Engine — adapter foundation implemented

- [x] Plan → approve → execute lifecycle.
- [x] Plan → approval → distributed FaaS dispatch lifecycle.
- [x] GAMGEE signed HTTPS installer function contract.
- [x] Proxmox worker FaaS function for template clone, CPU/RAM configure and VM start.
- [x] Kubernetes worker FaaS function for server-side apply Deployment + ClusterIP Service.
- [x] Deployment state reconciled from linked worker jobs.
- [ ] GAMGEE installer service and versioned bootstrap/upgrade contract.
- [ ] More hypervisor/cloud adapters (libvirt, OpenStack, public clouds, etc.).
- [ ] Bare-metal-to-Kubernetes bootstrap for independent PaaS.
- [ ] VM image lifecycle, cloud-init customization, networking and storage profiles.
- [ ] Rollback/compensation for partial multi-resource deployments.

## 5. Autonomous Operations Engine — policy and planning implemented

- [x] Worker metrics snapshots.
- [x] Scale-up/scale-in candidate recommendations with min/max bounds.
- [x] Basic HA readiness checks using enrolled nodes and failure domains.
- [x] Failover placement plan.
- [x] HAProxy backend configuration plan with input validation.
- [ ] Metrics time-series database, alert rules and SLOs.
- [ ] HAProxy/Envoy/cloud load-balancer apply and health verification.
- [ ] Approved autoscaling and node drain/replace workflows.
- [ ] Fencing, backup/restore and disaster-recovery execution.
- [ ] Closed-loop remediation with approvals, cooldowns and rollback.

## Production readiness gate

Do not expose the deployment APIs for production use until the system has SSO/RBAC, unique node identity, mTLS, secret-manager integration, signed worker artifacts, process-isolated FaaS, persistent shared database, security testing and tested recovery runbooks.
