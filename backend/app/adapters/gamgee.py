from __future__ import annotations

import hashlib
import hmac
import json
import ssl
import time
import urllib.request
from typing import Any


class GamgeeInstallerAdapter:
    """Adapter contract for an externally supplied, authenticated GAMGEE installer.

    GAMGEE's deployment API/installer contract must be implemented and versioned
    by the GAMGEE project. The Carpenter deliberately does not guess shell commands
    or bootstrap undocumented services.
    """

    def __init__(self, endpoint: str, secret: str, timeout: int = 60) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("GAMGEE installer endpoint must use HTTPS")
        if not secret:
            raise ValueError("GAMGEE installer signing secret is required")
        self.endpoint = endpoint
        self.secret = secret.encode()
        self.timeout = timeout

    def submit_bootstrap(self, plan: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(self.secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Carpenter-Timestamp": timestamp,
                "X-Carpenter-Signature": "sha256=" + digest,
            },
            method="POST",
        )
        context = ssl.create_default_context()
        try:
            with urllib.request.urlopen(request, context=context, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"GAMGEE installer request failed: {type(exc).__name__}") from exc
