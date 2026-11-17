# The Carpenter — AI Cloud Deployment Agent Architecture

## The system boundary

**The Carpenter is an AI Agent and the control plane. The user's servers and provider APIs are the data plane.**

The product is an AI Cloud Deployment Agent and AI Infrastructure-as-Code Agent. Users express desired outcomes in natural language; the agent discovers, designs, compiles, validates, provisions and reconciles supported infrastructure. Users do not manually author YAML or Terraform for supported resource types.

The Carpenter is not a hypervisor and does not require users to adopt GAMGEE. It coordinates infrastructure that the user owns or is authorised to manage.

Two destinations are supported by design:

1. **GAMGEE Cloud** — the Carpenter submits a signed bootstrap/expand request to a configured GAMGEE installer contract. GAMGEE is installed once for an environment; later nodes are joined and capacity is expanded.
2. **Own Cloud** — the user builds an independent cloud. The current IaaS adapter targets Proxmox VE; the PaaS adapter targets an existing Kubernetes API. These are deliberately separate from GAMGEE.

## Logical architecture

```text
                         USER
                          |
                Minimal Prompt Web UI
                          |
                 Python Control API
                          |
                THE CARPENTER AI AGENT
        Goal • Conversation • Reasoning • Planning
                          |
           +--------------+-------------------+
           |              |                   |
      Discovery       Resource Engine    AI IaC Engine
           |              |                   |
           +--------------+-------------------+
                          |
                 Validation / Policy
                          |
                 Deployment Engine
                          |
               Distributed Python FaaS
                Durable Queue / Registry
                  /       |       \
              Worker    Worker    Worker
               Node A    Node B    Node C
                  \       |       /
                   USER DATA PLANE
       Compute • Hypervisor • Storage • Network
                       |
             +---------+----------+
             |                    |
        GAMGEE Cloud            Own Cloud
        Optional path         IaaS / PaaS
             +---------+----------+
                       |
                 Operations Engine
           Metrics • HA • Failover • LB Plans
```

The web application, API, AI orchestration, IaC compiler, node agent, worker handlers and FaaS functions are Python. The browser UI is server-rendered HTML and CSS; no Node.js or JavaScript application runtime is used.

## Control plane responsibilities

- Prompt and conversation state.
- Natural-language goal interpretation and bounded desired-state extraction.
- Agent task orchestration and conversational clarification.
- Deterministic IaC compilation, artifact hashes and validation.
- Worker/function version registry and durable job queue.
- Node inventory, heartbeat freshness and capability catalogue.
- Resource assessment, placement and capacity forecasting.
- Deployment plans, approval policy, adapter selection and audit events.
- Telemetry evaluation, HA assessment, failover and load-balancer planning.

## Data plane responsibilities

- User-owned physical servers, VMs and hypervisors.
- Storage, network and workload runtimes.
- Worker-side read-only discovery/metrics functions and approved provider mutations.
- Execution of Carpenter-generated, allow-listed IaC resources using local provider credentials.
- GAMGEE or independent cloud services chosen by the user.
- Application and infrastructure telemetry.

## AI Agent and IaC pipeline

The Carpenter operates as a goal-driven infrastructure agent:

1. Interpret a natural-language outcome into a bounded desired-state request.
2. Discover enrolled hosts, hypervisors, storage/network facts and worker capabilities.
3. Select the target cloud/provider and plan resource placement.
4. Compile the validated request into a deterministic `carpenter.iac/v1` resource graph and provider YAML artifacts.
5. Verify schema, resource allow-lists, artifact hashes, fingerprint, capacity and worker capabilities.
6. Apply the generated resources through approved provider FaaS functions.
7. Reconcile the deployment from worker job outcomes and report results.

The model does not generate executable shell, arbitrary Python or unrestricted provider configuration. A deterministic Python compiler creates the IaC, and provider workers apply supported resource shapes. The user does not need to create the YAML manually.

Current compiler support is intentionally bounded: Proxmox VM plans, Kubernetes Deployment/Service manifests and GAMGEE bootstrap plans. General Terraform/OpenTofu and Ansible generation are not yet implemented. See [AI-AGENT.md](AI-AGENT.md) and [IAC-ENGINE.md](IAC-ENGINE.md).

## Distributed function execution

The control plane stores versioned function registrations and jobs in SQLite. Workers poll over an authenticated outbound HTTPS connection. Each job has:
- Function name and exact version.
- JSON input/output.
- Priority and maximum attempt count.
- Available-at timestamp, lease expiration and lease token.
- Worker identity and optional target-worker constraint.
- Idempotency key, result or failure detail.

A worker can claim only a function version it advertises in its heartbeat. Expired leases are re-queued until the attempt limit, then moved to the dead-letter state. Results are accepted only from the worker holding the active lease token before expiry.

The delivery guarantee is **at-least-once**, not exactly-once. Provider deployments are also FaaS functions: Proxmox VM creation, Kubernetes apply and the signed GAMGEE installer handoff run on selected data-plane workers. Provider credentials remain on those workers. All mutating functions must be idempotent or provide compensation. See [DISTRIBUTED-FAAS.md](DISTRIBUTED-FAAS.md).

## Discovery and assessment

The current discovery model uses explicitly enrolled node agents rather than scanning arbitrary address ranges. Heartbeats carry host facts, failure-domain labels, worker capabilities and hypervisor presence checks. Optional TCP probes accept explicit private IP literals and allow-listed ports only.

Inventory older than `CARPENTER_AGENT_STALE_SECONDS` is excluded from live capacity. Discovery reports reachability and capability; it does not infer that an arbitrary pingable machine is authorised or safe to manage.

## Resource engine

The first placement engine uses per-host CPU, memory and free-disk estimates, with default reserves of 15% CPU, 20% memory and 15% disk. Placement requires a detected virtualization capability. HA placement prefers distinct failure domains and refuses to claim HA if the configured nodes cannot span enough domains.

This is an advisory, conservative scheduler. It does not yet model NUMA, IOPS, network throughput, GPU scheduling, reservations for all existing workloads, power/network/storage shared failure modes or complex affinity rules.

## Deployment engine

Deployment is an AI Agent and IaC pipeline followed by a plan → approve → distributed apply lifecycle:
- The IaC compiler creates a deterministic resource graph and reviewable provider artifacts before any mutation.
- GAMGEE: signed HTTPS handoff to a GAMGEE installer service using a generated bootstrap/expand plan.
- Own-cloud IaaS: Proxmox VE worker applies a generated VM resource by cloning a pre-prepared cloud-init template, applying supported CPU/RAM settings and starting the VM.
- Own-cloud PaaS: Kubernetes worker applies the compiler-generated Deployment and ClusterIP Service YAML to an existing cluster.
- Hybrid: IaaS and PaaS components together.

Only a configured adapter can execute. There is no undocumented shell installer. The Proxmox adapter is restricted to the configured Proxmox node and template. The Kubernetes adapter requires a pre-existing API server and narrowly scoped service account.

## Operations engine

The current operations functions collect metrics, provide policy-bounded scale recommendations, assess basic HA readiness, calculate failover placement and render a proposed HAProxy backend configuration. They do not silently scale, fail over, write load-balancer configuration or restart services. Such actions need provider-specific adapters, approval policy and rollback semantics.

## Availability and elasticity rules

- Do not scale below configured minimum replicas or below the declared HA objective.
- Respect maximum capacity, resource headroom, quotas and budget policy.
- Check health before and after every operation.
- Drain connections before removing a load-balancer backend.
- Require fencing and data-consistency checks before failover.
- Keep a rollback/compensation plan for every infrastructure mutation.
- Treat AI output as a recommendation; deterministic policy and adapters enforce execution.

## Current production boundary

The repository is an early engineering foundation. SQLite and the local control plane are suitable for a single-instance development deployment, not a multi-replica HA control plane. Shared enrollment tokens, environment-based adapter secrets and the current prompt session model are not production-grade multi-tenant security. See [SECURITY.md](SECURITY.md).
