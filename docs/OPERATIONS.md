# Autonomous Operations Engine

## Current operation functions

- `operations.metrics_snapshot@1.0.0`: node CPU, RAM, root-disk and network counters.
- Scale decision policy: scale-out, scale-in candidate or hold, with min/max replica bounds and disk alerts.
- HA assessment: live nodes and distinct failure domains.
- Failover plan: re-place a workload estimate after a named failed node is excluded.
- Load-balancer plan: render a validated HAProxy frontend/backend configuration.

## Collect fleet metrics

`POST /api/v1/operations/metrics/collect` queues one targeted metrics job per online worker. Results are exposed through `GET /api/v1/operations/metrics`.

## HA readiness

`POST /api/v1/operations/ha-assessment` checks live-node count and distinct failure domains. It does not yet verify replicated storage, quorum, independent power, redundant network paths or application-level probes.

## Scale recommendations

`POST /api/v1/operations/recommendation` accepts:

```json
{
  "metrics": {"cpu_percent": 92, "memory_percent": 71, "root_disk_percent": 62},
  "policy": {
    "scale_up_threshold": 80,
    "scale_down_threshold": 25,
    "disk_alert_threshold": 85,
    "min_replicas": 2,
    "current_replicas": 3,
    "max_replicas": 12
  }
}
```

The response is a recommendation, not an executed scale action.

## Failover plan

`POST /api/v1/operations/failover-plan` accepts a failed node ID and the resource shape to recover. It calculates replacement placement among surviving nodes. It does not fence the failed host or move data.

Before failover execution, a future adapter must:
- Fence or otherwise prove the failed node cannot continue serving writes.
- Verify storage/data consistency and replica freshness.
- Check failure-domain and quorum rules.
- Verify capacity and networking.
- Require approval and capture a compensation plan.

## Load-balancer plan

`POST /api/v1/operations/load-balancer/plan` accepts an explicit list of backend IP literals and ports. It returns HAProxy text with HTTP health checks. The current implementation does not write the file, validate it with a running HAProxy binary, reload HAProxy, or drain connections.

## Production autonomy gates

Closed-loop autonomous operations are not enabled yet. Before enabling automatic scale/failover/load-balancer mutations, add:
- Persistent metrics history and SLO/alert evaluation.
- Policy scopes, budgets, cooldowns and rate limits.
- Provider adapters with dry-run, approval and rollback.
- Health checks before/after action.
- Maintenance windows and blast-radius controls.
- Audit export, alert routing and operations runbooks.
