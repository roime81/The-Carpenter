# Dual Cloud Deployment Engine

## Shared lifecycle

1. Create a deployment plan.
2. Review destination, model, placements, adapter readiness, capacity checks and HA checks.
3. Approve the exact saved plan.
4. Execute only if the saved plan reports ready and approved.
5. Inspect the result and audit events.

Endpoints use the admin header `X-Carpenter-Token`:
- `POST /api/v1/deployments/plan`
- `GET /api/v1/deployments/{deployment_id}`
- `POST /api/v1/deployments/{deployment_id}/approve`
- `POST /api/v1/deployments/{deployment_id}/execute`

Example plan:

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
    "high_availability":true,
    "name":"app-node"
  }'
```

The response includes `deployment_id` and readiness checks. Approve the same ID:

```bash
curl -X POST https://carpenter.example.com/api/v1/deployments/DEPLOYMENT_ID/approve \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approved_by":"infrastructure-owner"}'
```

Then execute:

```bash
curl -X POST https://carpenter.example.com/api/v1/deployments/DEPLOYMENT_ID/execute \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

Execution is not a substitute for production change management. Review all adapter settings, template contents, network rules, backups and rollback before approval.

## Option A — GAMGEE Cloud

The Carpenter includes a signed HTTPS handoff adapter. Configure:

- `CARPENTER_GAMGEE_INSTALLER_URL`
- `CARPENTER_GAMGEE_INSTALLER_TOKEN`

The endpoint is an integration contract; it must be implemented by the GAMGEE installer/control service. The Carpenter does not contain GAMGEE internals or guess a shell installer.

Request body fields:
- `deployment_id`: stable Carpenter deployment identifier (use for idempotency).
- `action`: `bootstrap-or-expand`.
- `service_model`: selected IaaS/PaaS/hybrid target.
- `requested`: saved user request.
- `placement`: capacity plan.
- `hosts`: enrolled host count.

Headers:
- `X-Carpenter-Timestamp`: Unix timestamp string.
- `X-Carpenter-Signature`: `sha256={hex(HMAC-SHA256(secret, timestamp + "." + raw_body))}`.

The GAMGEE endpoint should verify the HMAC in constant time, reject stale timestamps (recommended five-minute window), enforce idempotency on `deployment_id`, return JSON with the bootstrap/expansion operation ID, and report status separately. It must not trust arbitrary function/code fields from the request.

## Option B — Own Cloud IaaS with Proxmox VE

Configure:
- `CARPENTER_PROXMOX_URL=https://pve.example.com:8006`
- `CARPENTER_PROXMOX_TOKEN_ID=user@realm!token-name`
- `CARPENTER_PROXMOX_TOKEN_SECRET=...`
- `CARPENTER_PROXMOX_NODE=the-proxmox-node-name`
- `CARPENTER_PROXMOX_TEMPLATE_VMID=9000`

The referenced VM must be a prepared cloud-init-capable Proxmox template with the intended OS image and storage/network defaults. The configured node name must match an enrolled server that identifies itself as a Proxmox host. The API token needs only the permissions required for cloning, configuring and starting VMs.

The adapter:
1. Obtains the next VM ID from Proxmox.
2. Clones the configured template.
3. Waits for clone task completion.
4. Applies vCPU and memory sizing.
5. Waits for configuration completion.
6. Starts the VM and waits for its task.

It does not create or download an OS template, assign user SSH keys, customise per-VM cloud-init networking, configure firewall rules, or provision independent shared storage yet. Prepare and validate your template before enabling the adapter.

## Option B — Own Cloud PaaS with Kubernetes

Configure:
- `CARPENTER_KUBERNETES_API_URL=https://kube-api.example.com:6443`
- `CARPENTER_KUBERNETES_TOKEN=...`

The Kubernetes cluster and namespace must already exist. The token must be scoped to the selected namespace and only the required Deployment and Service operations.

A PaaS request requires:
- `container_image`
- `name`
- `namespace`
- `container_port`
- `vm_count` interpreted as desired replicas for PaaS

The adapter uses Kubernetes server-side apply to create/update a generated Deployment and ClusterIP Service. This first version does not bootstrap Kubernetes from bare metal, build a container registry, configure ingress/TLS, secrets, persistent volumes, autoscaling or service mesh.

## Hybrid

Hybrid combines the current Proxmox IaaS and existing-Kubernetes PaaS adapters. The Kubernetes cluster must exist before the PaaS portion can be deployed. If the overall workflow spans both providers, partial success is possible; the current version records failure but does not yet compensate by deleting successfully created components. Treat hybrid as an advanced, supervised operation.
