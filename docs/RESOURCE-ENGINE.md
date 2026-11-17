# Intelligent Resource Engine

## Placement input

The placement planner consumes fresh node heartbeats:
- CPU logical cores.
- Total and available memory.
- Free disk.
- Hypervisor capability.
- Failure-domain label.
- Online/offline state.

The engine uses a conservative default reserve:
- 15% CPU.
- 20% memory.
- 15% free disk.

It does not assume CPU overcommit. It attempts to place each VM onto a host with remaining CPU, memory and disk. A hypervisor capability must be detected before a node is eligible for VM placement.

## HA placement

When HA is requested, the planner prefers hosts in failure domains not yet used by the deployment. It does not claim HA if the requested VMs cannot be spread across at least two domains.

The HA assessment also checks the number of live nodes and distinct failure-domain labels. This is a topology hint, not proof of end-to-end availability: storage, power, network, quorum, upstream load balancers and control-plane dependencies must also be redundant.

Set `CARPENTER_FAILURE_DOMAIN` on each agent. Use meaningful labels such as `rack-a`, `rack-b`, `zone-1`, `zone-2` or independent sites. Do not simply assign different labels to nodes that share the same physical failure domain.

## Capacity forecast

`POST /api/v1/resources/forecast` accepts at least three samples containing `days_from_now` and `utilisation_percent`. It estimates a linear growth slope and time until a chosen threshold.

This is a basic advisory forecast, not an ML prediction. It has no automatic access to a historical metrics store yet; samples are supplied by an operator or upstream telemetry integration.

## API

`POST /api/v1/resources/plan` creates a non-mutating VM placement plan. Admin token required:

```json
{
  "destination": "own_cloud",
  "service_model": "iaas",
  "vm_count": 4,
  "vcpu_per_vm": 2,
  "memory_gb_per_vm": 8,
  "disk_gb_per_vm": 80,
  "high_availability": true
}
```

A plan is not a deployment. VM creation is performed only through the separate deployment plan → approval → execute workflow.
