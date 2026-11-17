# The Carpenter
### One Agent That Rules Them All.

**A minimalist, prompt-driven cloud launcher.** The user describes the outcome. The Carpenter assesses the user's servers, plans resource placement, coordinates cloud deployment and provides ongoing operations intelligence.

> **The Carpenter is the control plane. The user's servers are the data plane.** GAMGEE is optional: the user can ask The Carpenter to onboard GAMGEE Cloud or build an independent cloud.

The interface stays deliberately small: one web prompt, one agent, and conversational clarification. The platform complexity is implemented behind the prompt using native Python functions.

## Contents

- [Principles and architecture](#principles-and-architecture)
- [Implementation status](#implementation-status)
- [Quick start](#quick-start)
- [Enrol data-plane servers](#enrol-data-plane-servers)
- [Configure cloud adapters](#configure-cloud-adapters)
- [Use the deployment lifecycle](#use-the-deployment-lifecycle)
- [Operate and inspect](#operate-and-inspect)
- [API reference](#api-reference)
- [Tests](#tests)
- [Security and production readiness](#security-and-production-readiness)
- [Technical documentation](#technical-documentation)

---

## Principles and architecture

1. **Python 100%.** API, orchestration, model gateway, workers, infrastructure adapters and FaaS functions are Python. The browser UI is server-rendered HTML/CSS; there is no Node.js or JavaScript application runtime.
2. **Control plane / data plane separation.** The Carpenter controls; user-owned servers provide compute, storage and network.
3. **Two cloud choices.** GAMGEE onboarding or independent IaaS/PaaS/hybrid. Neither option is forced.
4. **Native Python FaaS.** Functions are registered, versioned and executed by trusted workers.
5. **Prompt-first experience.** No configuration-heavy infrastructure console.
6. **Safe execution.** The AI interprets and plans; typed functions and provider adapters execute. Infrastructure mutations follow plan → approval → execute.

```text
                 USER
                  |
          Minimal Web Prompt
                  |
            Python API
                  |
          THE CARPENTER AGENT
        Intent • Plan • Policy
                  |
         Distributed Python FaaS
        Queue • Versions • Leases
             /    |     \
          Node A Node B Node C
             \    |     /
             USER DATA PLANE
     Servers • Hypervisors • Storage
                  |
          +-------+--------+
          |                |
     GAMGEE CLOUD       OWN CLOUD
      optional          IaaS / PaaS
          +-------+--------+
                  |
            OPERATIONS ENGINE
        Metrics • HA • Failover • LB
```

## Implementation status

<badge color="success">CI tests passing</badge> <badge color="info">Early engineering foundation</badge>

| Programme | Implemented in this increment | Still required for production |
|---|---|---|
| Distributed Native FaaS | Durable SQLite queue, versioned function matching, targeted worker polling, leases, retries/backoff, idempotency keys, dead-letter status | Shared PostgreSQL queue, isolated workers, signed function packages, multi-tenant quotas |
| Infrastructure Discovery | Per-node CPU/RAM/disk/OS/network facts, KVM/libvirt/Proxmox detection, targeted read-only TCP probes | Hypervisor API inventory, IOPS/network benchmarks, GPU/NUMA and full failure-domain topology |
| Intelligent Resource Engine | Per-host placement, CPU/RAM/disk headroom, HA spread, simple capacity forecast | Reservations, workload-aware bin packing, NUMA/GPU/IOPS and cost models |
| Dual Cloud Deployment | Approved plans enqueue versioned GAMGEE, Proxmox and Kubernetes FaaS jobs on credentialed data-plane workers; deployment status reconciles from job results | GAMGEE installer service, bare-metal Kubernetes bootstrap, storage/network/image automation, multi-resource compensation |
| Autonomous Operations | Worker metrics, HA assessment, scale recommendations, failover placement and HAProxy config planning | Live SLO/alert pipeline, automatic adapter apply, health verification, fencing, drain, rollback and recovery |

**Important distinction:** provider operations are dispatched as native Python FaaS jobs to workers that advertise the required configured capability. Proxmox/Kubernetes/GAMGEE credentials live on those workers, not in the Carpenter control plane. The GAMGEE path is an integration contract; it needs a compatible installer endpoint. The own-cloud PaaS path targets an existing Kubernetes cluster; it does not yet bootstrap Kubernetes on raw servers.

---

## Quick start

### Requirements

- Docker Engine 24+.
- Docker Compose v2.
- Python 3.12+ on each data-plane server that will run a worker.
- A local TCP port (default 8000).

### 1. Clone and configure

```bash
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
cp .env.example .env
```

Generate two different secrets:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put one generated value in `CARPENTER_ADMIN_TOKEN` and a different one in `CARPENTER_AGENT_ENROLLMENT_TOKEN` in `.env`. Do not use the example placeholders.

For a local-only demo, leave cloud adapter settings empty. You can still run the prompt UI, inspect the health endpoint and exercise planning APIs.

### 2. Start The Carpenter control plane

```bash
docker compose up --build -d
docker compose logs -f carpenter
```

Open:

- **Prompt UI:** http://localhost:8000
- **Health:** http://localhost:8000/health
- **Interactive API docs:** http://localhost:8000/docs
- **Versioned function catalogue:** http://localhost:8000/api/v1/functions

Stop the platform:

```bash
docker compose down
```

The SQLite database is persisted in the `carpenter-data` Docker volume. To remove it as well, run `docker compose down -v` (destructive).

---

## Enrol data-plane servers

The Node Agent is both an inventory reporter and a distributed Python FaaS worker. Run it on every server that The Carpenter is authorised to manage. It makes outbound connections; it does not expose an inbound command listener.

### Linux

```bash
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
python3 -m venv .venv
source .venv/bin/activate
pip install -r node_agent/requirements.txt

export CARPENTER_URL="https://carpenter.example.com"
export CARPENTER_AGENT_TOKEN="the-same-node-enrolment-secret-from-.env"
export CARPENTER_FAILURE_DOMAIN="rack-a"
python node_agent/agent.py
```

### Windows PowerShell

```powershell
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r node_agent/requirements.txt

$env:CARPENTER_URL = "https://carpenter.example.com"
$env:CARPENTER_AGENT_TOKEN = "the-same-node-enrolment-secret-from-.env"
$env:CARPENTER_FAILURE_DOMAIN = "rack-a"
python node_agent/agent.py
```

Run one agent per server. Use meaningful failure domains such as `rack-a`, `rack-b`, `zone-1` or separate sites; nodes sharing a power/network/storage failure must not be assigned fake independent domains.

The agent sends heartbeats every 30 seconds and polls the FaaS queue every 2 seconds by default. Adjust with `CARPENTER_HEARTBEAT_SECONDS` and `CARPENTER_WORKER_POLL_SECONDS`. Nodes older than `CARPENTER_AGENT_STALE_SECONDS` (default 90 seconds) are excluded from live capacity.

Current built-in functions include read-only discovery/metrics plus provider functions for Proxmox VM creation, Kubernetes Deployment/Service apply and signed GAMGEE bootstrap. Provider functions are advertised only when the relevant worker has its endpoint and credentials configured. Workers execute only shipped, versioned Python handlers; they never execute arbitrary shell or model-generated Python.

For service management and the exact worker protocol, see [docs/DISTRIBUTED-FAAS.md](docs/DISTRIBUTED-FAAS.md).

---

## Configure cloud adapters

Provider credentials are stored on the specific data-plane execution workers, not in the Carpenter control-plane `.env`. A worker advertises its provider FaaS function only when its local configuration is complete. Restart the Node Agent after adding or changing a provider configuration.

### Option A — GAMGEE Cloud

On one trusted worker with network access to the GAMGEE installer endpoint:

```bash
export CARPENTER_GAMGEE_INSTALLER_URL="https://gamgee-installer.example.com/api/v1/bootstrap"
export CARPENTER_GAMGEE_INSTALLER_TOKEN="your-hmac-signing-secret"
```

That worker advertises `gamgee.bootstrap@1.0.0`. The installer endpoint must implement the signed request contract in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). This repository does not invent or bundle GAMGEE's installer internals.

### Option B — independent IaaS with Proxmox VE

On each Proxmox host that The Carpenter may use for VM placement:

```bash
export CARPENTER_PROXMOX_URL="https://pve.example.com:8006"
export CARPENTER_PROXMOX_TOKEN_ID="carpenter@pve!launcher"
export CARPENTER_PROXMOX_TOKEN_SECRET="your-proxmox-api-token-secret"
export CARPENTER_PROXMOX_NODE="pve-node-01"
export CARPENTER_PROXMOX_TEMPLATE_VMID="9000"
```

Prepare a cloud-init-capable VM template in Proxmox first. The agent must run on the configured Proxmox host. The worker advertises `compute.proxmox_deploy@1.0.0`. The adapter clones the template, applies vCPU/RAM sizing, waits for Proxmox tasks and starts one VM per FaaS job. Storage/network profiles, disk resizing and per-VM cloud-init customisation are not implemented yet.

### Option B — independent PaaS with Kubernetes

On a worker that can reach the intended Kubernetes API:

```bash
export CARPENTER_KUBERNETES_API_URL="https://kubernetes.example.com:6443"
export CARPENTER_KUBERNETES_TOKEN="your-narrowly-scoped-service-account-token"
```

The worker advertises `platform.kubernetes_deploy@1.0.0`. It deploys a generated Kubernetes Deployment and ClusterIP Service using server-side apply. The Kubernetes cluster and namespace must already exist. The service account should be restricted to the intended namespace and required resource types.

The current PaaS function does not bootstrap Kubernetes on bare metal. That is a future provider/bootstrap capability.

Full worker-side environment details and adapter contracts are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Use the deployment lifecycle

Create a plan first. Do not call execute directly without reviewing the plan.

### 1. Create a plan

```bash
curl -X POST http://localhost:8000/api/v1/deployments/plan \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "own_cloud",
    "service_model": "iaas",
    "vm_count": 2,
    "vcpu_per_vm": 4,
    "memory_gb_per_vm": 16,
    "disk_gb_per_vm": 100,
    "high_availability": true,
    "name": "app-node"
  }'
```

The response includes a `deployment_id`, capacity/HA/adapter readiness checks and a saved plan.

### 2. Approve the exact plan

```bash
curl -X POST http://localhost:8000/api/v1/deployments/DEPLOYMENT_ID/approve \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"approved_by":"infrastructure-owner"}'
```

### 3. Execute

```bash
curl -X POST http://localhost:8000/api/v1/deployments/DEPLOYMENT_ID/execute \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

Execution is refused unless the stored plan passed its readiness checks and was approved. The execute endpoint returns `queued` with FaaS job IDs; poll `GET /api/v1/deployments/DEPLOYMENT_ID` for linked worker status and results. A deployment becomes `succeeded` only after all linked jobs succeed. Hybrid deployments can partially succeed; compensation/rollback across independent providers is not yet implemented.

---

## Operate and inspect

### Inventory

```bash
curl http://localhost:8000/api/v1/inventory \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

### Queue discovery on every online node

```bash
curl -X POST http://localhost:8000/api/v1/discovery/scan \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

The response returns the targeted worker jobs. Results appear in `GET /api/v1/jobs`.

### Collect metrics from every online worker

```bash
curl -X POST http://localhost:8000/api/v1/operations/metrics/collect \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"

curl http://localhost:8000/api/v1/operations/metrics \
  -H "X-Carpenter-Token: $CARPENTER_ADMIN_TOKEN"
```

### HA, scaling and load-balancer planning

- `POST /api/v1/operations/ha-assessment`
- `POST /api/v1/operations/recommendation`
- `POST /api/v1/operations/failover-plan`
- `POST /api/v1/operations/load-balancer/plan`
- `GET /api/v1/operations/events`

These APIs produce assessments and plans. They do not yet perform autonomous load-balancer reloads, data failover or closed-loop scaling. See [docs/OPERATIONS.md](docs/OPERATIONS.md).

---

## API reference

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/api/v1/functions` | Function/version catalogue |
| GET | `/api/v1/inventory` | Enrolled node inventory (admin) |
| POST | `/api/v1/agents/heartbeat` | Worker heartbeat |
| POST | `/api/v1/jobs` | Enqueue FaaS job (admin) |
| GET | `/api/v1/jobs` | List jobs (admin) |
| GET | `/api/v1/jobs/{id}` | Get job result/status (admin) |
| POST | `/api/v1/workers/{id}/claim` | Claim work (worker) |
| POST | `/api/v1/workers/{id}/jobs/{job}/complete` | Complete leased job (worker) |
| POST | `/api/v1/workers/{id}/jobs/{job}/fail` | Fail leased job (worker) |
| POST | `/api/v1/discovery/scan` | Queue fleet discovery (admin) |
| POST | `/api/v1/resources/plan` | Non-mutating placement plan (admin) |
| POST | `/api/v1/resources/forecast` | Simple capacity forecast (admin) |
| POST | `/api/v1/deployments/plan` | Create dual-cloud deployment plan |
| GET | `/api/v1/deployments/{id}` | Read plan and reconcile linked FaaS job results |
| POST | `/api/v1/deployments/{id}/approve` | Approve saved plan |
| POST | `/api/v1/deployments/{id}/execute` | Dispatch approved provider FaaS jobs |
| POST | `/api/v1/operations/metrics/collect` | Queue node metrics |
| GET | `/api/v1/operations/metrics` | Read metrics job results |
| POST | `/api/v1/operations/ha-assessment` | HA readiness check |
| POST | `/api/v1/operations/recommendation` | Scale/operation recommendation |
| POST | `/api/v1/operations/failover-plan` | Recovery placement plan |
| POST | `/api/v1/operations/load-balancer/plan` | HAProxy config plan |
| GET | `/api/v1/operations/events` | Operation audit events |

Administrative endpoints require `X-Carpenter-Token`; worker endpoints require `X-Agent-Token`. Interactive API documentation is at `/docs`.

---

## Tests

Python 3.12+:

```bash
pip install -r requirements.txt
PYTHONPATH=backend python -m unittest discover -s tests -v
```

GitHub Actions runs the unit suite on pushes to `main` and pull requests.

---

## Security and production readiness

This is an early engineering foundation, not a production-ready multi-tenant cloud control plane.

- The node enrollment token is shared across workers in this first increment. Production requires per-node identity, short-lived credentials and mTLS.
- The browser prompt does not yet include production SSO/RBAC/CSRF controls.
- The queue is durable SQLite for a single control-plane instance. Multi-replica deployment needs shared transactional storage and distributed scheduling.
- Function versions are matched, but worker packages are not yet cryptographically signed or verified.
- FaaS is at-least-once. Mutating functions need idempotency and compensation.
- Proxmox, Kubernetes and GAMGEE credentials are kept in worker environment variables in this build; production requires per-worker identity and a secrets manager.
- PaaS requires an existing Kubernetes cluster; GAMGEE requires a compatible external installer endpoint.
- HA, failover, autoscaling and load balancing currently produce policies/plans; they are not fully autonomous closed-loop operations.

Read [docs/SECURITY.md](docs/SECURITY.md) before connecting real infrastructure.

## Technical documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Distributed FaaS](docs/DISTRIBUTED-FAAS.md)
- [Infrastructure Discovery](docs/DISCOVERY.md)
- [Resource Engine](docs/RESOURCE-ENGINE.md)
- [Dual Cloud Deployment](docs/DEPLOYMENT.md)
- [Autonomous Operations](docs/OPERATIONS.md)
- [Function Model](docs/FUNCTIONS.md)
- [Security](docs/SECURITY.md)
- [Engineering Roadmap](docs/ROADMAP.md)
- [Changelog](CHANGELOG.md)

## Repository structure

```text
.
├── backend/app/
│   ├── adapters/              # Direct adapter clients retained for reference/tests
│   ├── runtime/               # Local Python function runtime
│   ├── main.py                # FastAPI control plane
│   ├── store.py               # SQLite queue, worker and inventory store
│   ├── deployment_engine.py   # Plan/approve/execute coordinator
│   ├── resource_engine.py     # Placement and forecasting
│   ├── operations_engine.py   # HA, recovery and LB planning
│   └── worker_catalogue.py    # Versioned worker functions
├── node_agent/
│   ├── agent.py               # Outbound worker process
│   └── handlers.py            # Allow-listed local Python handlers
├── docs/
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## License

No license has been selected yet. Until one is added, all rights are reserved by the repository owner.
