from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any


class KubernetesAdapter:
    """Narrow Kubernetes API client; no arbitrary manifest or shell execution."""

    def __init__(self, api_url: str, bearer_token: str, timeout: int = 20) -> None:
        if not api_url.startswith("https://"):
            raise ValueError("Kubernetes API URL must use HTTPS")
        if not bearer_token:
            raise ValueError("Kubernetes bearer token is required")
        self.api_url = api_url.rstrip("/")
        self.token = bearer_token
        self.timeout = timeout
        self.context = ssl.create_default_context()

    def _apply(self, path: str, body: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self.api_url + path + "?fieldManager=the-carpenter",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/apply-patch+yaml",
                "Accept": "application/json",
            },
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            raise RuntimeError(f"Kubernetes API request failed: {type(exc).__name__}") from exc

    @staticmethod
    def _validate_name(value: str) -> None:
        if not value or len(value) > 63 or value.lower() != value:
            raise ValueError("Names must be lowercase DNS labels no longer than 63 characters")
        if not value[0].isalnum() or not value[-1].isalnum():
            raise ValueError("Names must begin and end with an alphanumeric character")
        if any(not (char.isalnum() or char == "-") for char in value):
            raise ValueError("Names may contain only lowercase letters, numbers and hyphens")

    def create_deployment(
        self, namespace: str, name: str, image: str, replicas: int,
        container_port: int,
    ) -> dict[str, Any]:
        self._validate_name(namespace)
        self._validate_name(name)
        if replicas < 1 or replicas > 100:
            raise ValueError("Replica count must be between 1 and 100")
        if not image or len(image) > 512 or any(char.isspace() for char in image):
            raise ValueError("A valid container image reference is required")
        if not 1 <= container_port <= 65535:
            raise ValueError("Container port is out of range")
        encoded = urllib.parse.quote(namespace, safe="")
        body = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": {"app": name}},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {"containers": [{
                        "name": name, "image": image,
                        "ports": [{"containerPort": container_port}],
                    }]},
                },
            },
        }
        deployment = self._apply(
            f"/apis/apps/v1/namespaces/{encoded}/deployments/{name}", body
        )
        service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name, "namespace": namespace},
            "spec": {
                "selector": {"app": name},
                "ports": [{"name": "http", "port": container_port,
                           "targetPort": container_port, "protocol": "TCP"}],
                "type": "ClusterIP",
            },
        }
        service_result = self._apply(
            f"/api/v1/namespaces/{encoded}/services/{name}", service
        )
        return {"deployment": deployment, "service": service_result}
