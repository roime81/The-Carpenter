from __future__ import annotations

import hashlib
import json
from typing import Any

import yaml


SCHEMA_VERSION = "carpenter.iac/v1"
SAFE_KINDS = {"virtual_machine", "kubernetes_deployment", "kubernetes_service", "gamgee_environment"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _kubernetes_manifests(request: dict[str, Any], deployment_id: str) -> list[dict[str, Any]]:
    name = request["name"]
    namespace = request["namespace"]
    image = request["container_image"]
    replicas = request["vm_count"]
    port = request["container_port"]
    labels = {
        "app": name,
        "app.kubernetes.io/managed-by": "the-carpenter",
        "carpenter.io/deployment-id": deployment_id,
    }
    return [
        {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [{
                            "name": name,
                            "image": image,
                            "ports": [{"name": "http", "containerPort": port, "protocol": "TCP"}],
                            "resources": {
                                "requests": {
                                    "cpu": str(request["vcpu_per_vm"]),
                                    "memory": f"{request['memory_gb_per_vm']}Gi",
                                },
                                "limits": {
                                    "cpu": str(request["vcpu_per_vm"]),
                                    "memory": f"{request['memory_gb_per_vm']}Gi",
                                },
                            },
                        }]
                    },
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": namespace, "labels": labels},
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": name},
                "ports": [{"name": "http", "port": port, "targetPort": port, "protocol": "TCP"}],
            },
        },
    ]


def compile_iac_bundle(
    deployment_id: str,
    request: dict[str, Any],
    placement: dict[str, Any] | None,
    execution_workers: dict[str, list[str]],
) -> dict[str, Any]:
    """Compile validated user intent into a deterministic, provider-aware IaC bundle.

    This is an internal compiler: users do not write or upload YAML/Terraform.
    The model supplies validated intent; this compiler emits the executable resource
    graph and human-reviewable provider artifacts. No secrets or executable scripts
    are embedded in the bundle.
    """
    if not deployment_id or len(deployment_id) > 64:
        raise ValueError("A valid deployment ID is required")

    destination = request["destination"]
    service_model = request["service_model"]
    resources: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    placements = (placement or {}).get("placements", [])

    if destination == "gamgee":
        resources.append({
            "resource_id": "gamgee-environment",
            "provider": "gamgee",
            "kind": "gamgee_environment",
            "spec": {
                "action": "bootstrap-or-expand",
                "service_model": service_model,
                "requested": request,
                "target_workers": execution_workers.get("gamgee", []),
                "target_nodes": [item.get("host_id") for item in placements],
            },
        })
        gamgee_doc = {
            "apiVersion": SCHEMA_VERSION,
            "kind": "InfrastructurePlan",
            "metadata": {"name": f"gamgee-{deployment_id[:8]}", "deploymentId": deployment_id},
            "spec": {"provider": "gamgee", "resources": resources},
        }
        artifacts.append(_artifact("gamgee-plan.yaml", yaml.safe_dump(gamgee_doc, sort_keys=False)))

    if destination == "own_cloud" and service_model in ("iaas", "hybrid"):
        vm_resources = []
        for item in placements:
            resource = {
                "resource_id": f"vm-{item['vm_name']}",
                "provider": "proxmox",
                "kind": "virtual_machine",
                "worker_id": item["host_id"],
                "spec": {
                    "name": item["vm_name"],
                    "vcpu": item["vcpu"],
                    "memory_gb": item["memory_gb"],
                    "disk_gb": item["disk_gb"],
                    "failure_domain": item.get("failure_domain", "default"),
                    "image_source": "preconfigured-cloud-init-template",
                },
            }
            vm_resources.append(resource)
            resources.append(resource)

        proxmox_doc = {
            "apiVersion": SCHEMA_VERSION,
            "kind": "InfrastructurePlan",
            "metadata": {"name": f"proxmox-{deployment_id[:8]}", "deploymentId": deployment_id},
            "spec": {"provider": "proxmox", "resources": vm_resources},
        }
        artifacts.append(_artifact("proxmox-plan.yaml", yaml.safe_dump(proxmox_doc, sort_keys=False)))

    if destination == "own_cloud" and service_model in ("paas", "hybrid"):
        manifests = _kubernetes_manifests(request, deployment_id)
        for manifest in manifests:
            resources.append({
                "resource_id": f"kubernetes-{manifest['kind'].lower()}-{request['name']}",
                "provider": "kubernetes",
                "kind": (
                    "kubernetes_deployment" if manifest["kind"] == "Deployment"
                    else "kubernetes_service"
                ),
                "spec": manifest,
            })
        artifacts.append(_artifact(
            "kubernetes-manifests.yaml",
            yaml.safe_dump_all(manifests, sort_keys=False),
        ))

    graph = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": deployment_id,
        "intent": {
            "destination": destination,
            "service_model": service_model,
            "request": request,
        },
        "resources": resources,
    }
    fingerprint = hashlib.sha256(_canonical(graph)).hexdigest()

    return {
        **graph,
        "fingerprint": fingerprint,
        "resource_count": len(resources),
        "artifacts": artifacts,
        "validation": {
            "schema_valid": True,
            "resource_kinds_allowlisted": all(item["kind"] in SAFE_KINDS for item in resources),
            "provider_secrets_embedded": False,
            "generated_code_embedded": False,
            "requires_policy_evaluation": True,
        },
        "execution_note": "Generated IaC is reviewed and applied by registered provider FaaS functions; it is not executed as shell or arbitrary code.",
    }


def _artifact(filename: str, content: str) -> dict[str, str]:
    return {
        "filename": filename,
        "content": content,
        "format": "yaml",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }



def validate_iac_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recalculate bundle and artifact hashes before a provider dispatch."""
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported Carpenter IaC schema version")
    resources = bundle.get("resources")
    if not isinstance(resources, list) or any(
        not isinstance(item, dict) or item.get("kind") not in SAFE_KINDS
        for item in resources
    ):
        raise ValueError("IaC bundle contains an unsupported resource kind")
    if bundle.get("validation", {}).get("provider_secrets_embedded") is not False:
        raise ValueError("Provider credentials must not be embedded in IaC")
    if bundle.get("validation", {}).get("generated_code_embedded") is not False:
        raise ValueError("Executable/generated code is not an IaC resource")
    graph = {
        "schema_version": bundle["schema_version"],
        "deployment_id": bundle["deployment_id"],
        "intent": bundle["intent"],
        "resources": resources,
    }
    expected = hashlib.sha256(_canonical(graph)).hexdigest()
    if bundle.get("fingerprint") != expected:
        raise ValueError("IaC bundle fingerprint does not match its resource graph")
    for artifact in bundle.get("artifacts", []):
        content = artifact.get("content", "")
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != artifact.get("sha256"):
            raise ValueError(f"IaC artifact hash mismatch: {artifact.get('filename', 'unknown')}")
        if artifact.get("format") != "yaml":
            raise ValueError("Only YAML IaC artifacts are supported by this compiler")
        list(yaml.safe_load_all(content))
    return {
        "valid": True,
        "fingerprint": expected,
        "resource_count": len(resources),
        "artifact_count": len(bundle.get("artifacts", [])),
    }
