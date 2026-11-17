# The Carpenter
### One Agent That Rules Them All.

The Carpenter is a minimalist, web-based, AI-first infrastructure launcher. Describe the outcome you want; The Carpenter inventories reachable infrastructure, assesses capacity, proposes a deployment plan, and coordinates approved provisioning and GAMGEE Cloud onboarding.

> **Status: foundation / MVP scaffold.** The repository starts empty. This initial implementation provides the web prompt experience, API contract, discovery workflow skeleton, safe planning boundary, and local deployment. It does **not** yet provision production VMs, configure hypervisors, or install GAMGEE automatically. Those operations require provider-specific adapters, credentials, integration tests, and explicit approval gates.

## Product principle

**One prompt. One orchestrator. Many execution modules.**

The interface stays deliberately small:
- Product identity: **The Carpenter — One Agent That Rules Them All**
- One conversational prompt bar.
- The agent asks only the next necessary question.
- Progress and results appear as conversation messages, not an infrastructure dashboard.

The orchestration layer is modular behind the single agent. It is not a collection of user-facing configuration screens.

## User journey

1. **Describe the outcome** — e.g. “Create a highly available PaaS environment for 3 services.”
2. **Connect infrastructure** — user supplies a managed connector or installs a Carpenter Node Agent on each server/cluster. Credentials are stored outside the chat.
3. **Discover and verify** — perform authenticated inventory and reachability checks. ICMP ping is a useful signal, but not proof that a host is manageable. The agent checks the registered agent/SSH/API channel and reports partial reachability accurately.
4. **Assess capacity** — CPU, memory, storage, network, virtualization support, existing workloads, failure domains, and constraints.
5. **Clarify intent** — ask how many VMs, sizing, region/site, and whether the target is **IaaS**, **PaaS**, or a recommended combination.
6. **Propose a plan** — show resource allocation, topology, risks, estimated capacity, HA design, and actions. No infrastructure mutation occurs before approval.
7. **Provision** — execute idempotent provider-specific actions with checkpoints, timeouts, audit events, and rollback/compensation where possible.
8. **Install GAMGEE once** — bootstrap the GAMGEE control plane after prerequisites pass; then join additional nodes and distribute workloads for larger deployments.
9. **Operate** — monitor health and utilisation; recommend scale-up/down or execute pre-approved policies. HA and load balancing must be backed by health checks, capacity headroom, failure-domain awareness, and safe drain/rollback.

## Architecture

```text
 User
  |
  v
 Minimal Web UI (single prompt)
  |
  v
 Carpenter API / Conversation Gateway
  |
  v
 The Carpenter Agent (intent, questions, planning)
  |
  +--> Discovery & Inventory
  +--> Capacity Assessment & Placement
  +--> Policy / Approval / Audit
  +--> Provisioning Orchestrator
  |      +--> Bare metal / hypervisor adapters
  |      +--> Cloud IaaS adapters
  |      +--> Network / storage adapters
  +--> GAMGEE Bootstrap & Cluster Join
  +--> Operations: telemetry, HA, autoscaling, load balancing
  |
  v
 Managed Infrastructure + GAMGEE Cloud
```

### Design boundaries

- **Agent = planner and coordinator.** It never receives unrestricted shell access and must not invent successful actions.
- **Execution = deterministic adapters.** Each adapter validates inputs, enforces policy, emits structured results, and supports idempotency.
- **Node Agent = trusted execution boundary.** Outbound authenticated connection, least privilege, signed jobs, allowlisted operations, short-lived credentials, and audit logging.
- **Approval = explicit.** Discovery is read-only. Provisioning, deletion, network changes, and GAMGEE installation require a human-approved plan unless a narrowly scoped policy explicitly authorises them.
- **Secrets = never chat.** Use a secret manager or encrypted credential store; redact tokens and private keys from logs.
- **Provider-neutral core.** Hypervisor/cloud integrations are plug-in adapters. Do not hard-code one vendor into the orchestration domain.

## Repository layout

```text
.
├── frontend/                 # Minimal React + TypeScript prompt UI
├── backend/                  # FastAPI service and workflow contracts
│   └── app/
│       ├── api/               # HTTP endpoints
│       ├── services/          # Discovery and planning services
│       └── models/             # Typed request/response models
├── docs/
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   └── ROADMAP.md
├── docker-compose.yml
├── .env.example
└── README.md
```

## Quick start (Docker)

Requirements: Docker Engine 24+, Docker Compose v2, and ports 3000 and 8000 available.

```bash
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
cp .env.example .env
docker compose up --build
```

Open:
- Web UI: http://localhost:3000
- API health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

The default local mode is a safe demo. It does not scan arbitrary networks or execute infrastructure changes.

## Local development

### Backend

Python 3.12+ recommended.

```bash
cd backend
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

Node.js 20+.

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` in `frontend/.env.local` if the API is not using the default URL.

## Configuration

See [.env.example](.env.example). Never commit real credentials. In production, terminate TLS at a trusted ingress, restrict origins, configure authentication/SSO, use a secret manager, and isolate the node-agent network.

## API foundation

- `GET /health` — liveness.
- `POST /api/v1/sessions` — create a conversation session.
- `POST /api/v1/sessions/{session_id}/messages` — submit a prompt and receive the next agent response.
- `POST /api/v1/discovery` — start a read-only discovery job for registered targets (adapter implementation required).
- `POST /api/v1/plans` — create a proposed infrastructure plan.
- `POST /api/v1/plans/{plan_id}/approve` — approval boundary; execution adapter is not enabled in this scaffold.

## Deployment model

Start with one Carpenter control plane and one or more Node Agents. For larger estates, run a highly available Carpenter control plane behind a reverse proxy and deploy node agents close to each infrastructure failure domain. The control plane should remain stateless where possible; persist sessions, inventory snapshots, plans, approvals, and audit events in a production database.

GAMGEE onboarding should be a one-time bootstrap per environment, followed by secure node registration and cluster expansion. Do not reinstall the control plane when adding capacity.

## Scaling and high availability

The future operations engine should combine:
- Metrics and service health, not CPU alone.
- Predictive and threshold-based recommendations with explainable reasons.
- Scale-up/down policies with cooldowns, minimum/maximum bounds, and budget limits.
- Load-balancer health checks, connection draining, and safe failback.
- Placement across independent hosts / racks / zones where available.
- Capacity reservations and N+1 (or user-selected) failure tolerance.

Autoscaling must never silently reduce capacity below the declared availability objective.

## Security

Read [docs/SECURITY.md](docs/SECURITY.md) before connecting real infrastructure. The MVP is not production-ready for privileged infrastructure operations.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md). The intended progression is discovery → assessment → plan → approval → provisioning adapters → GAMGEE bootstrap → operations/HA → multi-site distributed deployments.

## License

No license has been selected yet. Until one is added, all rights are reserved by the repository owner.
