# Dual Cloud Deployment Engine — Distributed FaaS

## Execution model

The Carpenter control plane never calls hypervisor, Kubernetes or GAMGEE provider APIs during deployment execution. It validates the approved plan and enqueues versioned Python functions on selected data-plane workers.

The deployment lifecycle is:

1. Create and persist a plan.
2. Inspect placement, HA checks and available worker capabilities.
3. Approve the saved plan.
4. Revalidate live inventory and placement immediately before dispatch.
5. Enqueue provider functions as distributed FaaS jobs.
6. Workers execute provider APIs using credentials configured locally on those workers.
7. The control plane reconciles deployment status from linked job results.

The deployment API returns `queued` after dispatch. It does not claim that infrastructure has been created until all required jobs report success.

## Worker-side provider configuration

The provider credentials belong on the specific execution worker, not the Carpenter control plane. The worker advertises the provider function capability only when the required local configuration is present.

### Option A — GAMGEE Cloud

On one trusted worker with network access to the GAMGEE installer endpoint:

```bash
export CARPENTER_GAMGEE_INSTALLER_URL="https://gamgee-installer.example.com/api/v1/bootstrap"
export CARPENTER_GAMGEE_INSTALLER_TOKEN="your-hmac-signing-secret"
```

Restart the Node Agent after adding these variables. It advertises `gamgee.bootstrap@1.0.0`.

The worker sends a signed request containing:
- `deployment_id`: stable Carpenter deployment ID, required for idempotency.
- `action`: `bootstrap-or-expand`.
- `service_model`: IaaS/PaaS/hybrid target.
- `requested`: saved user requirements.
- `placement`: VM/host placement assessment.
- `hosts` and `target_nodes`: data-plane inventory context.

Headers:
- `X-Carpenter-Timestamp`: Unix timestamp string.
- `X-Carpenter-Signature`: `sha256={hex(HMAC-SHA256(secret, timestamp + "." + raw_body))}`.

The GAMGEE installer endpoint must verify the HMAC in constant time, reject stale timestamps (recommended five-minute window), enforce idempotency on `deployment_id`, and return a terminal JSON status of `succeeded` or `completed` with an operation ID/result. The current worker function does not poll a separate asynchronous status API; an `accepted` or `queued` response is treated as incomplete and retried. The endpoint must complete the bootstrap/expand operation synchronously within the worker timeout, or a later Carpenter release must add a dedicated GAMGEE status-poll function. It must not trust arbitrary function/code fields from the request.

### Option B — Own Cloud IaaS with Proxmox VE

Configure each Proxmox Node Agent that is allowed to receive VM jobs:

```bash
export CARPENTER_PROXMOX_URL="https://pve.example.com:8006"
export CARPENTER_PROXMOX_TOKEN_ID="carpenter@pve!launcher"
export CARPENTER_PROXMOX_TOKEN_SECRET="your-proxmox-api-token-secret"
export CARPENTER_PROXMOX_NODE="pve-node-01"
export CARPENTER_PROXMOX_TEMPLATE_VMID="9000"
```

The agent must run on the Proxmox host and its failure-domain label must describe the real rack/zone/site. The referenced VM must be a prepared cloud-init-capable Proxmox template with OS image and storage/network defaults. The API token should have only the permissions required to list cluster resources, obtain VM IDs, clone, configure and start VMs.

The worker:
1. Looks for an existing VM with the deterministic Carpenter VM name (retry reconciliation).
2. Obtains the next free VM ID when no VM exists.
3. Clones the prepared template.
4. Waits for the Proxmox clone task.
5. Applies vCPU and RAM sizing.
6. Starts the VM and waits for task completion.
7. Returns each VM ID and result in the FaaS job result.

The initial Proxmox function targets an installed Proxmox worker and its configured node. Multiple nodes can advertise the function and receive separate VM jobs, allowing the resource planner to spread placement across configured workers. This does not yet implement advanced cluster placement or storage/network profile selection. It does not download OS images, assign per-user SSH keys, resize arbitrary template disks, or create firewall/network resources.

### Option B — Own Cloud PaaS with Kubernetes

Configure one or more Node Agents that can reach the intended Kubernetes API and have a narrowly scoped service account:

```bash
export CARPENTER_KUBERNETES_API_URL="https://kube-api.example.com:6443"
export CARPENTER_KUBERNETES_TOKEN="your-namespace-scoped-service-account-token"
```

Restart the Node Agent. It advertises `platform.kubernetes_deploy@1.0.0`.

A PaaS request requires:
- `container_image`
- `name`
- `namespace`
- `container_port`
- `vm_count` interpreted as desired replicas

The worker uses Kubernetes server-side apply to create/update a generated Deployment and ClusterIP Service. The Kubernetes cluster and namespace must already exist. The service account should be restricted to the intended namespace and only the required Deployment and Service resources.

This first version does not bootstrap Kubernetes from bare metal, build a container registry, configure ingress/TLS, secrets, persistent volumes, HPA, service mesh or storage classes.

## Create, approve and dispatch a deployment

All control-plane deployment endpoints require the admin header `X-Carpenter-Token`.

- `POST /api/v1/deployments/plan`
- `GET /api/v1/deployments/{deployment_id}`
- `POST /api/v1/deployments/{deployment_id}/approve`
- `POST /api/v1/deployments/{deployment_id}/execute`

Create a plan:

```bash
curl -X POST https://carpenter.example.com/api/v1/deployments/plan \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "destination":"own_cloud",
    "service_model":"iaas",
    "vm_count":2,
    "vcpu_per_vm":4,
    "memory_gb_per_vm":16,
    "disk_gb_per_vm":100,
    "high_availability":false,
    "name":"app-node"
  }'
```

Review the `deployment_id`, placement, execution worker IDs and readiness checks. Approve the same plan:

```bash
curl -X POST https://carpenter.example.com/api/v1/deployments/DEPLOYMENT_ID/approve \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approved_by":"infrastructure-owner"}'
```

Dispatch approved FaaS jobs:

```bash
curl -X POST https://carpenter.example.com/api/v1/deployments/DEPLOYMENT_ID/execute \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

The response has `status: queued` and the job IDs. Track completion:

```bash
curl https://carpenter.example.com/api/v1/deployments/DEPLOYMENT_ID \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

The deployment record reports linked jobs, worker IDs, attempts, errors and results. It becomes `succeeded` only when all linked jobs succeed; a dead-lettered job marks the deployment `failed`.

## Hybrid deployments

Hybrid queues separate IaaS and PaaS functions. It can partially succeed if one provider succeeds and the other fails. The current release does not yet perform cross-provider compensation (for example, deleting successful VMs after the Kubernetes job fails). Review partial results and carry out controlled remediation.

## Idempotency and at-least-once execution

FaaS delivery is at-least-once. Stable deployment IDs and idempotency keys prevent duplicate job submission. Worker functions also use deterministic VM names or Kubernetes server-side apply to reconcile a retry. The GAMGEE installer must enforce idempotency by deployment ID.

Do not interpret a successful FaaS dispatch as a successful deployment; poll the saved deployment until it reaches a terminal state.
