# Native Python FaaS Function Model

## Contract

Infrastructure capabilities are represented as registered Python functions. The runtime accepts JSON-compatible dictionaries and returns structured dictionaries. Functions must be deterministic where practical and idempotent for mutating operations.

## Current functions

| Function | Purpose | Side effects |
|---|---|---|
| `assessment.capacity` | Aggregate enrolled-node CPU and memory inventory | None |
| `planning.deployment` | Produce a preliminary VM capacity plan | None |
| `operations.scaling_recommendation` | Recommend scale-up, scale-down review, or hold | None |

## Planned function domains

- `discovery.*`: node/provider discovery, health and capability probing.
- `compute.*`: VM create, resize, stop, start and delete.
- `network.*`: virtual networks, subnets, security rules, routing and load balancing.
- `storage.*`: volumes, snapshots, attachment and backup.
- `platform.*`: PaaS services, runtime deployment and service discovery.
- `gamgee.*`: one-time bootstrap, node join, upgrade and health.
- `operations.*`: telemetry, autoscaling, remediation and recovery.

## Required function metadata

Every production function must declare:
- Name and semantic version.
- Input and output schema.
- Required capabilities and privilege level.
- Worker execution limit and retry policy.
- Idempotency requirements and concurrency behaviour.
- Approval class (read-only, low-risk mutation, privileged mutation, destructive).
- Compensation/rollback strategy.
- Audit event and telemetry fields.

## Execution model

The agent must never generate arbitrary shell commands and pass them directly to a worker. The planner selects a registered function and creates a typed invocation. The policy layer validates it. The approval service authorises it. The worker executes only the registered handler.

The current implementation is an in-process proof of concept with a thread pool and process-local, best-effort idempotency cache. A caller timeout does not terminate a running Python thread. Run only trusted, short-lived functions in this runtime. Production execution must use isolated worker processes or containers, a durable queue, worker leases, retry/dead-letter handling, persistent idempotency and signed versioned function packages.
