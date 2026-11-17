# The Carpenter — Architecture

## Core model

**The Carpenter is the control plane. The user's servers are the data plane.**

The Carpenter does not own or silently replace the user's infrastructure. It observes enrolled resources, assesses what they can support, proposes an outcome, and coordinates explicitly approved actions through provider-specific adapters.

There are two destination choices:

1. **GAMGEE Cloud** — bootstrap GAMGEE once on the selected infrastructure, then add nodes and expand the GAMGEE environment as capacity grows.
2. **Own Cloud** — build the requested IaaS, PaaS, or hybrid environment using supported hypervisor, network, storage, and runtime adapters. GAMGEE is not a dependency in this path.

## Logical architecture

```text
                 USER
                  |
          Minimal Web Prompt
                  |
          Python Web/API Layer
                  |
         THE CARPENTER AGENT
       intent / questions / plan
                  |
       Policy + Approval Boundary
                  |
       Native Python FaaS Runtime
       /       |       |          \
  Discovery Assessment Provision  Operations
       |       |       |          |
       +-------+-------+----------+
                  |
       Secure Node / Provider APIs
                  |
       USER-OWNED DATA PLANE
       servers / hypervisors / cloud
                  |
        +---------+-----------+
        |                     |
   GAMGEE Cloud            Own Cloud
   optional path           independent path
```

The UI is a server-rendered Python web application. It has no Node.js application runtime and no JavaScript framework.

## Control-plane responsibilities

- Conversation and intent capture.
- Infrastructure enrolment and inventory aggregation.
- Capacity assessment and placement planning.
- Target selection: GAMGEE or own cloud.
- Cloud model selection: IaaS, PaaS, or hybrid.
- Policy, approval, audit and workflow state.
- Function scheduling and lifecycle orchestration.
- Telemetry evaluation and scale recommendations.

## Data-plane responsibilities

- Physical servers, virtualisation hosts, storage and networks.
- VM and workload execution.
- GAMGEE services when that destination is selected.
- User-selected IaaS/PaaS components in the independent-cloud path.
- Workload health and metrics exported to the control plane.

## Conversation lifecycle

1. User describes the desired outcome.
2. User enrolls each server or cluster through the outbound node agent or a future provider connector.
3. The Carpenter verifies agent identity and receives a host inventory heartbeat.
4. The assessment functions calculate aggregate CPU, memory and storage indicators. Placement must later include NUMA, storage IOPS, network, GPU, failure-domain and reserved-capacity constraints.
5. The Carpenter asks how many VMs or workloads are required.
6. It asks whether to onboard GAMGEE or build an independent cloud.
7. It asks for IaaS, PaaS or hybrid.
8. The planner generates a reviewable plan.
9. A human approves the plan and a compatible adapter executes it.
10. The operations functions monitor health and recommend or apply bounded scaling policies.

## Native Python FaaS

The function runtime is the common execution substrate. Each operation is an allow-listed Python function with:
- A unique name and typed input/output contract.
- Bounded execution time.
- Invocation identifier and structured result.
- Idempotency key support (process-local in the MVP).
- Policy checks before privileged actions.
- Audit and telemetry hooks.

Initial functions:
- `assessment.capacity`
- `planning.deployment`
- `operations.scaling_recommendation`

Future function domains include discovery, image management, VM lifecycle, network configuration, storage lifecycle, load-balancer updates, backup, recovery and GAMGEE bootstrap.

The current runtime is local and process-based. It is not yet a distributed FaaS scheduler. The roadmap adds durable queues, worker registration, leases, retries, dead-letter handling, and distributed placement.

## Availability and elasticity

The AI may recommend; a deterministic policy engine must enforce:
- Minimum and maximum capacity.
- Failure-domain and anti-affinity rules.
- N+1 or explicitly chosen redundancy.
- Resource headroom and reservations.
- Cooldowns, rate limits and budget boundaries.
- Health checks, connection draining and rollback.

A server count alone is not an HA design. A multi-node deployment must verify independent failure domains and the availability of network, storage and control-plane dependencies.
