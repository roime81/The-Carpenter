# The Carpenter — AI Cloud Deployment Agent

## Product definition

The Carpenter is an **AI Cloud Deployment Agent** and **AI Infrastructure-as-Code (IaC) Agent**.

It accepts an infrastructure or cloud outcome in natural language and takes responsibility for translating that outcome into a validated, provider-specific implementation. Users should not need to write YAML, Terraform, Ansible, cloud-init or provider API payloads for capabilities supported by the agent.

The core promise is:

> Tell The Carpenter what you want to build. The Carpenter discovers, designs, compiles, validates, provisions and verifies it.

The Carpenter is not merely a chatbot that explains commands, nor a visual front end for manually authored IaC. It owns the infrastructure workflow.

## Agent operating loop

```text
USER GOAL (natural language)
          |
          v
1. UNDERSTAND
   Intent • Workload • Constraints • Desired outcome
          |
          v
2. DISCOVER
   Servers • Hypervisors • Storage • Network • Providers
          |
          v
3. DESIGN
   Target architecture • Placement • Capacity • HA
          |
          v
4. COMPILE IaC
   Desired-state IR • Provider resources • YAML artifacts
          |
          v
5. VALIDATE
   Schema • Fingerprint • Capability • Capacity • Policy
          |
          v
6. AUTHORISE
   Approval policy • Scope • Change boundary
          |
          v
7. PROVISION
   Distributed Python FaaS • Provider workers
          |
          v
8. RECONCILE
   Job results • Resource status • Errors • Drift (future)
          |
          v
9. REPORT
   What was created • Where • Outputs • Remaining actions
```

The AI handles intent interpretation and planning. Deterministic Python engines compile the desired state and enforce the supported operations. The FaaS workers apply the generated resource graph through provider APIs.

## What the user provides

The user states the outcome and relevant business constraints, for example:

```text
Build an internal PaaS environment for my inventory API.
Run three replicas, with two vCPU and four GB RAM each.
Use this container image and expose it inside the private network.
Place workloads across available capacity where possible.
```

The agent may ask for information that materially changes the deployment, such as the target cloud, image reference, capacity, data location or exposure requirement. It should not ask the user to translate the request into YAML or Terraform.

## What The Carpenter produces

For supported providers the agent creates:
- A typed desired-state request.
- A resource graph with dependencies and placement.
- Provider-specific IaC documents.
- A bundle fingerprint and artifact hashes.
- A validation result and explicit blockers.
- Versioned FaaS jobs targeted to workers with the necessary provider capability.
- A deployment record that reconciles job results.

The generated bundle is retained with the deployment plan and can be inspected through:

`GET /api/v1/deployments/{deployment_id}/iac`

## AI and deterministic execution boundary

The model is not permitted to generate executable shell, Python, arbitrary Terraform providers, Kubernetes plugins or provider credentials.

The model extracts bounded intent fields. The Python IaC compiler maps those fields to a finite allow-list of supported resource kinds. The policy and deployment engines verify that the resources are supported, that the required worker capabilities exist, and that capacity/HA checks pass. Provider workers accept only their own supported resource shapes.

This design gives the product AI-driven planning without granting an LLM unrestricted infrastructure execution privileges.

## Onboarding responsibilities

The long-term target is for the agent to handle infrastructure onboarding as part of a natural-language task:
- Discover enrolled infrastructure.
- Assess server, hypervisor, storage and network capabilities.
- Identify available provider adapters.
- Build the target cloud or platform configuration.
- Generate the configuration artefacts internally.
- Apply the configuration with registered provider functions.
- Verify the resulting resources.

**Current release boundary:** a Python Node Agent must first be installed and enrolled on each host, and provider credentials must be configured on the worker authorised to use that provider. Automatic remote bootstrap of arbitrary bare-metal servers, SSH credential onboarding and general-purpose cluster installation are not implemented yet. Once a host/provider worker is enrolled, discovery and supported provisioning are orchestrated by The Carpenter.

## Approval and autonomy

The system separates planning from privileged mutation.

The current release saves a plan and its IaC bundle, requires authenticated administrative approval, then dispatches provider FaaS jobs. It does not silently provision infrastructure merely because a user has opened the prompt UI.

The intended product direction is policy-bounded autonomy:
- Read-only discovery can run automatically on enrolled nodes.
- Low-risk changes may be eligible for pre-authorised policy scopes in a future release.
- Resource creation, public exposure, identity changes, network/security changes and destructive operations require explicit approval unless an administrator has configured a tightly scoped policy.
- Every operation is versioned, attributable, auditable and reconcilable.

Conversational approval and user identity integration require SSO/RBAC in the prompt experience; the current admin API is the approval boundary.

## Current implemented capabilities

- Natural-language extraction for deployment model, VM count, CPU, memory, disk, image, port and HA intent.
- Automatic discovery job scheduling for newly online workers.
- Deterministic resource placement and worker selection.
- Deterministic IaC bundle compilation with Proxmox, Kubernetes and GAMGEE resource definitions.
- Kubernetes Deployment and Service YAML generation.
- SHA-256 fingerprinting and artifact integrity checks.
- Provider FaaS dispatch and deployment result reconciliation.

## Not yet implemented

- General-purpose Terraform/OpenTofu generation and plan/apply lifecycle.
- Ansible playbook generation or arbitrary configuration-management execution.
- Automatic SSH/bootstrap of unenrolled bare-metal servers.
- Full hypervisor inventory and Kubernetes cluster topology discovery.
- Broad provider ecosystem and arbitrary workload blueprints.
- Continuous drift detection and automatic remediation.
- Full authenticated conversational approval workflow.

The agent must never claim that these features are available until their provider functions, policy controls, tests and recovery workflows are implemented.
