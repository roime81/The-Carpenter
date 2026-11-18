# Engineering Roadmap — AI Cloud Deployment Agent

The Carpenter is being developed as an AI Cloud Deployment Agent and AI Infrastructure-as-Code Agent. The five engine programmes are the execution foundation behind that agent.

## 0. AI Agent and internal IaC — first vertical slice implemented

- [x] Natural-language extraction for deployment intent and workload sizing.
- [x] Discovery automatically queued for newly enrolled online workers.
- [x] Provider and capacity selection for the first supported cloud paths.
- [x] Deterministic `carpenter.iac/v1` desired-state/resource-graph compiler.
- [x] Proxmox, Kubernetes and GAMGEE IaC artifact generation.
- [x] Kubernetes Deployment and Service YAML generation from natural language requirements.
- [x] SHA-256 graph fingerprint and artifact hash validation.
- [x] IaC artifacts stored with the deployment plan and exposed for review.
- [x] Provider worker functions apply supported generated resource shapes.
- [ ] Broader multi-step LLM task planning and task memory.
- [ ] Conversational, authenticated approval/execution workflow.
- [ ] General-purpose Terraform/OpenTofu generation and plan/apply.
- [ ] Ansible/configuration-management generation with a constrained module catalogue.
- [ ] Continuous drift detection, reconciliation and controlled remediation.
- [ ] Automatic SSH/bootstrap of unenrolled bare-metal servers.

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
- [ ] Remote first-time server bootstrap and secure node enrolment.

## 3. Intelligent Resource Engine — first planner implemented

- [x] Conservative per-host placement using CPU, RAM and free disk.
- [x] Configurable reserve model (initial defaults: 15% CPU, 20% memory, 15% disk).
- [x] HA-aware spread across declared failure domains.
- [x] Basic linear capacity forecast from supplied time-series samples.
- [ ] Live reservation accounting and scheduler reconciliation.
- [ ] NUMA/GPU/IOPS/network-aware bin packing.
- [ ] Cost and power-aware placement.
- [ ] Predictive models trained from retained telemetry and workload seasonality.

## 4. Dual Cloud Deployment Engine — distributed provider apply implemented

- [x] Plan → approval → distributed FaaS dispatch lifecycle.
- [x] Deterministic internal IaC generated and saved with every deployment plan.
- [x] GAMGEE signed HTTPS installer function contract and generated bootstrap plan.
- [x] Proxmox worker FaaS function for template clone, CPU/RAM configure and VM start.
- [x] Kubernetes worker FaaS function applies generated Deployment/Service manifests.
- [x] Deployment state reconciled from linked worker jobs.
- [ ] GAMGEE installer service and versioned bootstrap/upgrade contract.
- [ ] More hypervisor/cloud adapters (libvirt, OpenStack, public clouds, etc.).
- [ ] Bare-metal-to-Kubernetes bootstrap for independent PaaS.
- [ ] VM disk resizing, image lifecycle, cloud-init customisation, networking and storage profiles.
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


## 6. Infrastructure Digital Twin 2.0 — planned pipeline

**Status: future programme / not implemented in 0.7.0.** The 0.7.0 Digital Twin provides the first durable observed-resource graph for Carpenter-managed workers, Proxmox and namespace-scoped Kubernetes. Version 2.0 is reserved for broader multi-cloud coverage, trustworthy reconciliation and controlled closed-loop operations. Work should proceed in the following order; do not enable automated remediation before the observation and approval gates are complete.

### Phase A — broaden topology coverage

- [ ] AWS inventory adapter for accounts, regions, VPCs, subnets, routes, security groups, compute, load balancers, managed Kubernetes, databases and storage.
- [ ] Azure inventory adapter for subscriptions, resource groups, VNets/subnets, NSGs, compute, AKS, managed services and storage.
- [ ] GCP inventory adapter for projects, regions/zones, VPCs/subnets/firewall rules, compute, GKE, managed services and storage.
- [ ] Expand Kubernetes from namespace-scoped inventory to permission-aware cluster topology: Nodes, conditions, taints, zones, Ingress/Gateway, NetworkPolicy, StorageClass, CSI/PV topology, events and controller ownership.
- [ ] Deepen Proxmox inventory for bridges/VLANs, pools, storage backends, guest NICs/disks, HA groups and cluster relationships.
- [ ] Define provider capability, permission and inventory-scope manifests so the twin can distinguish unsupported, forbidden, unavailable and successfully empty collections.
- [ ] Complete the GAMGEE observed-resource adapter and define stable provider-native IDs for its resources.

### Phase B — continuous reconciliation and lifecycle history

- [ ] Add scheduled inventory refresh policies per provider, account/cluster, region, namespace and worker.
- [ ] Persist inventory run records with scope, start/end, provider, worker, coverage, warnings, cursor and completeness evidence.
- [ ] Add resource lifecycle states and tombstones; infer deletion only after an authoritative, complete scan of the exact resource scope or an explicit provider deletion event.
- [ ] Track resource moves, replacements and provider identity changes without collapsing unrelated resources.
- [ ] Add point-in-time topology snapshots, historical graph queries and resource lineage across deployments.
- [ ] Add safe backoff, rate limits, pagination, API quota handling and resumable discovery.

### Phase C — desired-versus-observed drift intelligence

- [ ] Compare observed resources with the saved Carpenter IaC desired-state graph and explicit ownership/adoption records.
- [ ] Classify drift (configuration, capacity, availability, network exposure, storage, security policy, unmanaged resource and missing resource).
- [ ] Show drift diffs, evidence, first/last observed times, impact/dependency blast radius and confidence in the resource inspector.
- [ ] Add policy packs for security, resilience, naming, tagging, cost guardrails and approved architecture standards.
- [ ] Separate unmanaged resources, externally managed resources and Carpenter-managed resources; never assume ownership from observation alone.
- [ ] Support drift waivers, expiry, exception ownership and audit history.

### Phase D — approved remediation and operational control

- [ ] Generate a proposed remediation plan from a drift finding, with preconditions, blast-radius analysis and deterministic IaC diff.
- [ ] Require human approval for mutating operations by default; enforce role, policy, scope, change window and explicit resource ownership.
- [ ] Execute changes through existing versioned FaaS/provider adapters with idempotency, lease safety and immutable audit records.
- [ ] Verify the post-change provider state and reconcile the twin only from returned observations.
- [ ] Add rollback/compensation and stop conditions for partial failure; never promise rollback where the provider operation is irreversible.
- [ ] Keep autonomous remediation disabled until policy simulation, approval, rollback and recovery tests pass.

### Phase E — scale, resilience and operator experience

- [ ] Move high-volume shared inventory/event workloads from SQLite to a shared transactional data store with migration and backup strategy.
- [ ] Add incremental graph deltas or a durable event transport when polling-backed SSE is no longer sufficient.
- [ ] Add topology search, filtering, grouping, dependency tracing, blast-radius exploration and time-travel comparison.
- [ ] Add health, capacity, cost, security and compliance overlays without conflating inferred scores with provider-reported status.
- [ ] Add tenant/project isolation and authorization filters before exposing shared multi-account or multi-tenant topology.
- [ ] Define retention, archival, export and disaster-recovery policies for resource observations and topology snapshots.

### Digital Twin 2.0 exit criteria

- [ ] Provider coverage and permission boundaries are visible for every inventory scope; a partial or failed scan can never masquerade as complete.
- [ ] Stable identities and relationships are tested across accounts, regions, clusters, resource moves and provider re-creation.
- [ ] Deletion/tombstone inference is backed by complete-scope evidence or provider events and is auditable.
- [ ] Desired-versus-observed drift findings are reproducible from retained snapshots and policy versions.
- [ ] Every proposed mutation has an ownership check, policy decision, approval record, execution trace and post-change verification.
- [ ] Failure-injection tests demonstrate safe handling of throttling, expired credentials, partial scans, worker loss, duplicate events and failed compensation.

**Sequencing rule:** complete Phase A before broad drift claims; complete Phase B before deletion inference; complete Phase C before remediation proposals; and complete Phase D safety gates before enabling any autonomous changes. Until then, the Digital Twin remains an observation and decision-support system, not an autonomous infrastructure mutator.

## Production readiness gate

Do not expose the deployment APIs for production use until the system has SSO/RBAC, unique node identity, mTLS, secret-manager integration, signed worker artifacts, process-isolated FaaS, persistent shared database, security testing and tested recovery runbooks.
