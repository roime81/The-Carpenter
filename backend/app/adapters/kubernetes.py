from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from typing import Any


class KubernetesAdapter:
    """Minimal Kubernetes API adapter for creating namespaced Deployments/Services.

    This is a narrow API client, not a general manifest executor. It only creates
    validated Carpenter-generated resources and always validates the API server TLS.
    """

    def __init__(self, api_url: str, bearer_token: str, timeout: int = 20) -> None:
        if not api_url.startswith("https://"):
            raise ValueError("Kubernetes API URL must use HTTPS")
        if not bearer_token:
            raise ValueError("Kubernetes bearer token is required")
        self.api_url = api_url.rstrip("/")
        self.token = bearer_token
        self.timeout = timeout
        self.context = ssl.create_default_context()

    def _put(self, path: str, body: dict[str, Any]) -> Any:
        request = urllib.request.Request(
            self.api_url + path,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except Exception as exc:
            raise RuntimeError(f"Kubernetes API request failed: {type(exc).__name__}") from exc

    def create_deployment(
        self, namespace: str, name: str, image: str, replicas: int,
        container_port: int,
    ) -> dict[str, Any]:
        for value in (namespace, name):
            if not value.replace("-", "").isalnum() or value.lower() != value:
                raise ValueError("Namespace and deployment names must be lowercase DNS labels")
        if replicas < 1 or replicas > 100:
            raise ValueError("Replica count must be between 1 and 100")
        if not image or len(image) > 512 or any(char.isspace() for char in image):
            raise ValueError("A valid container image reference is required")
        if not 1 <= container_port <= 65535:
            raise ValueError("Container port is out of range")

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
        encoded = urllib.parse.quote(namespace, safe="")
        return self._put(f"/apis/apps/v1/namespaces/{encoded}/deployments", body)
