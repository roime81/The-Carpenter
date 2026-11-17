# Roadmap

## Milestone 0 — Prompt-first foundation (current)
- Minimal server-rendered web prompt in Python.
- SQLite-backed conversation history.
- Node heartbeat and basic host inventory.
- Local Python FaaS runtime with bounded wait and structured invocation results.
- Preliminary capacity assessment and non-mutating plan generation.
- Optional Ollama and OpenAI-compatible intent extraction.
- Docker Compose deployment.

## Milestone 1 — Discovery and assessment
- Unique node identity, secure enrolment and revocation.
- CPU, memory, disk, network, GPU, hypervisor, storage and failure-domain capability discovery.
- Freshness tracking and health state.
- Capacity model with reservations and configurable headroom.
- Assessment report and plan persistence.

## Milestone 2 — Cloud adapters
- GAMGEE bootstrap adapter and one-time environment registration.
- Independent-cloud adapters for selected hypervisors and cloud providers.
- Explicit IaaS/PaaS/hybrid capability matrix.
- VM image catalogue, network and storage profiles.
- Approval service and auditable plan execution.

## Milestone 3 — Distributed native FaaS
- Durable job queue and persistent invocation records.
- Worker registration, leases, retries and dead-letter queues.
- Function versioning, signatures and rollback.
- Placement by locality, capability and failure domain.
- Distributed execution across large server fleets.

## Milestone 4 — Operations and resilience
- Metrics ingestion and service-level objectives.
- AI-assisted recommendations with deterministic guardrails.
- HA-aware scaling, load-balancer updates, draining and rollback.
- Budget and quota constraints.
- Backup, restore, disaster recovery and maintenance workflows.

## Milestone 5 — Production readiness
- Multi-tenant RBAC, SSO and audit exports.
- High-availability control plane and database.
- Secrets manager integration and mTLS.
- Security testing, upgrade strategy, observability and operational runbooks.
- Conformance tests for every infrastructure adapter.

## Explicit non-goal
The Carpenter must not become a configuration-heavy infrastructure portal. The prompt remains the primary user interface; detailed inventory and execution data are surfaced conversationally or as generated reports only when useful.
