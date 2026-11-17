# The Carpenter
### One Agent That Rules Them All.

**The Carpenter is a prompt-driven cloud launcher.** Users describe the cloud outcome they want. The Carpenter discovers enrolled infrastructure, assesses capacity, clarifies the deployment target, prepares a plan, and (through future verified adapters) provisions and operates the selected environment.

The product has one primary interface: a minimalist web page with one prompt bar. The complexity belongs in the control plane, not in the user's workflow.

> **Current status: runnable foundation / early MVP.** This repository contains the Python web control plane, prompt conversation, node-inventory heartbeat, optional local LLM intent extraction, and a small Python-native FaaS function runtime. It currently produces preliminary plans only. It does not yet create VMs, install hypervisors, deploy PaaS services, bootstrap GAMGEE, or make autonomous load-balancer changes.

---

## 1. Product principles

- **The Carpenter is the control plane.** It understands intent, assesses, plans, enforces policy and coordinates execution.
- **The user's servers are the data plane.** Their compute, storage, network and hypervisor resources host the resulting cloud.
- **Two destinations, never one forced platform:**
  - **Onboard GAMGEE Cloud** — install GAMGEE once on the selected environment, then register additional nodes and expand it.
  - **Build my own cloud** — independently provision the user's chosen IaaS, PaaS or hybrid stack. GAMGEE is not a dependency.
- **Python 100%.** Application, API, orchestration, AI gateway, node agent and FaaS functions are Python. The web interface is server-rendered HTML/CSS; there is no Node.js or JavaScript application runtime.
- **Native FaaS execution.** Discovery, assessment, provisioning, networking, storage, monitoring, scaling and recovery are independently registered Python functions.
- **One agent, many specialised functions.** The model interprets intent; deterministic, allow-listed functions do the work. The model never gets unrestricted shell or infrastructure credentials.
- **Approval before mutation.** Discovery and assessment are read-only. VM creation, network changes, storage changes, installation and deletion require explicit approval and a compatible execution adapter.

## 2. User experience and workflow

The user might type:

> "I have six servers. Build a highly available PaaS environment for my applications."

The Carpenter follows a conversational process:

1. **Connect** — the user installs the Carpenter Node Agent on the servers or connects a supported infrastructure provider.
2. **Discover** — nodes report in through an authenticated outbound connection. Ping alone is not treated as proof of manageability.
3. **Assess** — collect host facts and calculate preliminary capacity. The full target assessment will include CPU, RAM, storage performance, networking, hypervisor capability, GPU, existing workloads and failure domains.
4. **Ask VM/workload requirements** — clarify the requested VM count, sizing and workload needs.
5. **Choose destination** — ask whether the user wants GAMGEE Cloud or their own cloud.
6. **Choose cloud model** — ask for IaaS, PaaS or hybrid.
7. **Plan** — calculate placement, headroom, HA requirements, risks and the execution sequence.
8. **Approve and build** — a future adapter executes the approved plan as idempotent functions with checkpoints and compensation.
9. **Operate** — monitor health and utilisation; recommend or apply bounded scaling and load-balancer changes under policy.

The sequence is intentionally conversational. The user should not need to open a collection of infrastructure configuration screens.

## 3. Architecture

```text
                         USER
                          |
                 Minimal Web Prompt
                          |
                Python Web / API Layer
                          |
                  THE CARPENTER
             Intent • Conversation • Plan
                          |
                 Policy / Approval
                          |
              Native Python FaaS Runtime
             /       |        |          \
       Discovery  Assessment Provision  Operations
             \       |        |          /
                          |
              Secure Node / Provider APIs
                          |
                 USER DATA PLANE
        Servers • Hypervisors • Storage • Network
                    /             \
             GAMGEE CLOUD       OWN CLOUD
              optional       IaaS / PaaS / Hybrid
```

### Control plane

- Prompt interface and conversation state.
- LLM gateway for constrained intent extraction.
- Node enrolment and inventory aggregation.
- Capacity assessment and placement.
- Deployment plan, policy, approval and audit.
- Native FaaS registration, invocation and lifecycle orchestration.
- Telemetry evaluation, HA and scaling decisions.

### Data plane

- Physical servers and virtualisation hosts.
- Compute, storage, network, images and workload runtimes.
- GAMGEE services only when the user chooses that path.
- User-selected cloud services on the independent-cloud path.
- Workload health and infrastructure telemetry.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design boundaries and flow.

## 4. Native Python FaaS

Every infrastructure capability is designed as a versioned Python function. The current local runtime supports registration, structured input/output, invocation IDs, wait timeouts and process-local idempotency.

| Function | Current responsibility | Status |
|---|---|---|
| `assessment.capacity` | Aggregate CPU and memory from enrolled nodes | Implemented |
| `planning.deployment` | Produce preliminary VM capacity plan | Implemented |
| `operations.scaling_recommendation` | Recommend scale-up / review scale-down / hold | Implemented |
| `discovery.*` | Full capability and topology discovery | Roadmap |
| `compute.*` | VM lifecycle and resizing | Adapter required |
| `network.*` | Networks, routing, security and load balancers | Adapter required |
| `storage.*` | Volumes, snapshots and backup | Adapter required |
| `gamgee.*` | One-time bootstrap, node join and upgrades | GAMGEE integration required |

The current runtime is an **in-process foundation**, not yet a distributed FaaS scheduler. Distributed workers, durable queues, leases, retry/dead-letter handling, signed function packages, function versioning and rollback are planned. See [docs/FUNCTIONS.md](docs/FUNCTIONS.md).

## 5. AI model integration

The AI gateway can use:
- **Ollama** for local/open-source models.
- **OpenAI-compatible endpoints** for other self-hosted or commercial model services.
- **Deterministic fallback** when no model is configured.

The model is deliberately constrained to extract user intent (VM count, GAMGEE vs own cloud, and IaaS/PaaS/hybrid). The backend validates those fields. It cannot invoke infrastructure functions, generate executable code for workers, or access secrets.

### Configure Ollama

Run Ollama on a host reachable from the Carpenter container and pull a model, for example:

```bash
ollama pull llama3.1:8b
```

Set these values in `.env`:

```dotenv
CARPENTER_LLM_PROVIDER=ollama
CARPENTER_LLM_MODEL=llama3.1:8b
CARPENTER_LLM_BASE_URL=http://host.docker.internal:11434
```

For an OpenAI-compatible service, set `CARPENTER_LLM_PROVIDER=openai-compatible`, configure `CARPENTER_LLM_BASE_URL` to its `/v1` base URL, and provide `CARPENTER_LLM_API_KEY` only when required. Do not commit API keys.

## 6. Quick deployment with Docker

### Requirements

- Docker Engine 24 or later.
- Docker Compose v2.
- A free local TCP port (default: 8000).

### Install

```bash
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
cp .env.example .env
```

Edit `.env` and replace `CARPENTER_AGENT_ENROLLMENT_TOKEN` with a long random secret. Do not use the sample placeholder in a real environment.

Start the control plane:

```bash
docker compose up --build -d
docker compose logs -f carpenter
```

Open:

- **The Carpenter UI:** http://localhost:8000
- **Health check:** http://localhost:8000/health
- **API documentation:** http://localhost:8000/docs
- **Registered FaaS catalogue:** http://localhost:8000/api/v1/functions

Stop it:

```bash
docker compose down
```

Persistent SQLite data is stored in the `carpenter-data` Docker volume. To remove the database as well, use `docker compose down -v` (destructive).

## 7. Run locally without Docker

Python 3.12+ is recommended.

### Linux / macOS

```bash
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CARPENTER_AGENT_ENROLLMENT_TOKEN="replace-with-a-long-random-secret"
export CARPENTER_DB_PATH="./data/carpenter.db"
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

### Windows PowerShell

```powershell
git clone https://github.com/roime81/The-Carpenter.git
cd The-Carpenter
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:CARPENTER_AGENT_ENROLLMENT_TOKEN = "replace-with-a-long-random-secret"
$env:CARPENTER_DB_PATH = ".\data\carpenter.db"
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

## 8. Enrol a server (Node Agent)

The Node Agent is a small Python process installed on each server that the user wants The Carpenter to assess. It makes an outbound heartbeat request; it does not listen for remote commands and does not execute arbitrary code.

On each target server, copy or clone the repository and install the agent requirement:

```bash
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .\.venv\Scripts\Activate.ps1
pip install -r node_agent/requirements.txt
```

Set the control-plane URL and the same enrolment token configured on The Carpenter.

Linux / macOS:

```bash
export CARPENTER_URL="https://carpenter.example.com"
export CARPENTER_AGENT_TOKEN="your-enrolment-token"
python node_agent/agent.py
```

Windows PowerShell:

```powershell
$env:CARPENTER_URL = "https://carpenter.example.com"
$env:CARPENTER_AGENT_TOKEN = "your-enrolment-token"
python node_agent/agent.py
```

The agent sends a heartbeat every 30 seconds by default. Override with `CARPENTER_HEARTBEAT_SECONDS` (minimum 15). Nodes older than the configured freshness window are excluded from live capacity; the default is 90 seconds (`CARPENTER_AGENT_STALE_SECONDS`). The initial inventory includes hostname, operating system, architecture, logical CPU count, RAM, disk totals/free space and IPv4 addresses.

The sample enrolment token is shared across nodes and intended only for the foundation milestone. Production requires unique node identities, per-node credentials, mutual TLS or equivalent workload identity, revocation and tenant isolation.

## 9. Tests and CI

Run the unit tests locally:

```bash
# Linux / macOS
PYTHONPATH=backend python -m unittest discover -s tests -v

# Windows PowerShell
$env:PYTHONPATH = "backend"
python -m unittest discover -s tests -v
```

GitHub Actions runs the Python unit test suite on pushes to `main` and pull requests.

## 10. API surface

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Prompt web UI |
| `GET` | `/health` | Liveness |
| `GET` | `/api/v1/functions` | Registered native Python functions |
| `POST` | `/api/v1/agents/heartbeat` | Authenticated node inventory heartbeat |
| `POST` | `/prompt` | Submit a prompt from the web UI |

FastAPI's interactive API documentation is available at `/docs`.

## 11. Current limitations — read before production

This is the first engineering foundation, not yet a production cloud installer.

- Inventory is agent-based; it does not sweep arbitrary IP ranges.
- Capacity planning currently evaluates CPU and memory only. Disk is collected but not yet used in placement; storage performance, network, GPU, hypervisor, NUMA and failure-domain logic are still required.
- The planning function assumes a simple per-VM sizing input. It is not yet a placement scheduler.
- VM provisioning and provider/hypervisor adapters are not implemented.
- GAMGEE bootstrap, independent PaaS/IaaS assembly and distributed workload placement are not implemented.
- Scaling is a recommendation function; it is not connected to a live telemetry pipeline or load balancer.
- The FaaS runtime and idempotency cache are process-local, not distributed or durable.
- The demo has no production authentication, multi-tenant authorisation or hardened CSRF/session setup. Do not expose it directly to the public internet or use it for privileged production infrastructure.

The security boundary and mandatory work before enabling mutations are described in [docs/SECURITY.md](docs/SECURITY.md).

## 12. Engineering roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md). The sequence is discovery → assessment → adapter framework → approval and provisioning → GAMGEE/own-cloud deployment → distributed FaaS → operations/HA → production hardening.

## 13. Repository structure

```text
.
├── backend/
│   └── app/
│       ├── main.py             # Python web/API entry point
│       ├── orchestrator.py     # Conversation state machine
│       ├── llm.py              # Optional Ollama/OpenAI-compatible intent gateway
│       ├── functions.py        # Native Python FaaS function catalogue
│       ├── runtime/faas.py     # Local FaaS runtime
│       ├── store.py            # SQLite persistence
│       ├── templates/          # Server-rendered prompt UI
│       └── static/             # Minimal CSS
├── node_agent/                 # Outbound Python inventory agent
├── docs/
├── tests/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## License

No license has been selected yet. Until one is added, all rights are reserved by the repository owner.
