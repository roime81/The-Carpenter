# AI Infrastructure-as-Code Engine

## Purpose

The IaC engine translates the agent's validated desired state into deterministic provider-specific resource definitions. It is internal to The Carpenter. The user does not have to author or upload YAML/Terraform for supported resource types.

## Compilation model

```text
Natural-language intent
       |
Validated request (Pydantic)
       |
Resource placement and provider selection
       |
Carpenter desired-state resource graph
       |
Provider IaC artifacts (YAML)
       |
Static validation + SHA-256 fingerprint
       |
Saved deployment plan
       |
Approved distributed FaaS apply
```

The first compiler version lives in `backend/app/iac_engine.py`. It is deterministic: given the same deployment ID, request, placement and worker selections, it emits the same resource graph and fingerprint.

## Bundle structure

A generated IaC bundle contains:
- `schema_version`: `carpenter.iac/v1`.
- `deployment_id`: immutable deployment identity.
- `intent`: validated request.
- `resources`: allow-listed provider resource graph.
- `artifacts`: reviewable YAML files, content and SHA-256 hashes.
- `fingerprint`: SHA-256 of the canonical resource graph.
- `validation`: schema and safety assertions.

The bundle does not contain provider credentials, arbitrary shell commands or generated executable code.

## Current resource kinds

| Provider | Resource kind | Generated representation | Apply function |
|---|---|---|---|
| Proxmox | `virtual_machine` | Carpenter `InfrastructurePlan` YAML and typed VM resource | `compute.proxmox_deploy@1.0.0` |
| Kubernetes | `kubernetes_deployment` | Kubernetes apps/v1 Deployment YAML | `platform.kubernetes_deploy@1.0.0` |
| Kubernetes | `kubernetes_service` | Kubernetes v1 ClusterIP Service YAML | `platform.kubernetes_deploy@1.0.0` |
| GAMGEE | `gamgee_environment` | Carpenter bootstrap/expand plan YAML | `gamgee.bootstrap@1.0.0` |

## Kubernetes example

For a PaaS workload, the compiler generates a Deployment and Service from the validated request. Replica count, image, application port, CPU and memory sizing are translated into the manifests. The worker receives the structured documents and their IaC fingerprint.

Before making any API call, the worker validates:
- Exactly one Deployment and one Service are present.
- Only supported API versions and resource kinds are used.
- Resource names and namespaces are valid DNS labels.
- Workload replicas and container port are within bounds.
- The image reference is syntactically safe.
- Service selector and target port match the Deployment.

The worker then uses Kubernetes server-side apply with its locally configured service-account token. Arbitrary manifests and custom resource definitions are not accepted in this version.

## Proxmox example

The compiler emits a Carpenter-owned YAML plan and a typed `virtual_machine` resource for each placed VM. The resource carries the worker placement, CPU, memory, disk request and prepared-template source.

The Proxmox worker receives one VM resource per FaaS job. It uses a deterministic name to reconcile retries, clones the configured cloud-init template, applies supported CPU/RAM settings, starts the VM and returns the VM ID.

**Current apply boundary:** disk-size intent is represented in the generated plan but automatic Proxmox disk resizing, custom storage profiles, network profiles and per-VM cloud-init customisation are not yet applied by the worker. The result must not be interpreted as proof those settings were enforced.

## Fingerprints and tamper detection

The compiler canonicalises the resource graph using sorted JSON keys and hashes it with SHA-256. Each YAML artifact also has a content hash.

Before provider FaaS dispatch, the control plane:
1. Verifies the schema version.
2. Checks every resource kind against the allow-list.
3. Confirms credentials and executable code are not embedded.
4. Recomputes the resource graph fingerprint.
5. Verifies every artifact hash.
6. Parses the YAML with safe loading.

A changed bundle or artifact is rejected before dispatch.

## Inspect the generated IaC

After a deployment plan has been created:

`GET /api/v1/deployments/{deployment_id}/iac`

The endpoint returns the resource graph, YAML artifacts, fingerprint and validation report. It is intended for transparency, review, audit and export. Editing the returned YAML is not part of the current execution path; change the natural-language requirements and ask the agent to generate a new plan instead.

## Extension contract

New IaC providers must implement:
1. A typed desired-state schema.
2. A deterministic compiler from desired state to allow-listed resources.
3. Schema and policy validation.
4. Artifact fingerprinting.
5. A versioned worker FaaS apply function.
6. Idempotent create/update/reconcile behaviour.
7. Explicit delete/rollback semantics before destructive operations are enabled.
8. Unit, integration and provider conformance tests.

Terraform/OpenTofu, libvirt, OpenStack, public-cloud resources, network/storage, identity, secrets, load balancing and bare-metal bootstrap are future compiler/provider modules—not implied capabilities of the current YAML compiler.
