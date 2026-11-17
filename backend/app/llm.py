from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

logger = logging.getLogger("carpenter.llm")

SYSTEM_PROMPT = """You are the intent parser for The Carpenter, an infrastructure control plane.
Return JSON only with optional keys:
vm_count (integer), destination ("gamgee" or "own_cloud"), service_model ("iaas", "paas", or "hybrid"),
vcpu_per_vm (integer), memory_gb_per_vm (integer), disk_gb_per_vm (integer),
high_availability (boolean), container_image (string), container_port (integer),
name (lowercase DNS label), namespace (lowercase DNS label).
Only extract values the user explicitly stated. Do not infer missing sizing, invent images,
names, destinations or HA requirements. Do not output commands, scripts, shell, function names,
credentials, or infrastructure instructions. The backend validates every extracted value and
is the only component allowed to invoke registered functions."""


class ModelGateway:
    """Optional local/open-source or OpenAI-compatible intent extraction.

    The model extracts constrained conversational slots only. It cannot execute tools,
    run code, access credentials, or mutate infrastructure.
    """

    def extract_slots(self, prompt: str) -> dict[str, Any]:
        provider = settings.llm_provider.lower()
        if provider in ("", "none", "disabled"):
            return {}
        try:
            if provider == "ollama":
                content = self._ollama(prompt)
            elif provider == "openai-compatible":
                content = self._openai_compatible(prompt)
            else:
                logger.warning("Unsupported LLM provider: %s", provider)
                return {}
            return self._validate(json.loads(content))
        except (ValueError, KeyError, TypeError, urllib.error.URLError, TimeoutError) as exc:
            logger.warning("LLM intent extraction unavailable; using deterministic fallback: %s", exc)
            return {}

    def _ollama(self, prompt: str) -> str:
        body = {
            "model": settings.llm_model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        request = urllib.request.Request(
            settings.llm_base_url.rstrip("/") + "/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["message"]["content"]

    def _openai_compatible(self, prompt: str) -> str:
        body = {
            "model": settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = "Bearer " + settings.llm_api_key
        request = urllib.request.Request(
            settings.llm_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    @staticmethod
    def _valid_dns_label(value: Any) -> bool:
        return (
            isinstance(value, str)
            and len(value) <= 63
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", value) is not None
        )

    @classmethod
    def _validate(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        result: dict[str, Any] = {}

        integer_fields = {
            "vm_count": (1, 10000),
            "vcpu_per_vm": (1, 256),
            "memory_gb_per_vm": (1, 4096),
            "disk_gb_per_vm": (1, 100000),
            "container_port": (1, 65535),
        }
        for field, (minimum, maximum) in integer_fields.items():
            value = raw.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum:
                result[field] = value

        if raw.get("destination") in ("gamgee", "own_cloud"):
            result["destination"] = raw["destination"]
        if raw.get("service_model") in ("iaas", "paas", "hybrid"):
            result["service_model"] = raw["service_model"]
        if isinstance(raw.get("high_availability"), bool):
            result["high_availability"] = raw["high_availability"]

        image = raw.get("container_image")
        if (
            isinstance(image, str)
            and 1 <= len(image) <= 512
            and not any(char.isspace() or ord(char) < 32 for char in image)
            and not image.startswith("-")
        ):
            result["container_image"] = image

        for field in ("name", "namespace"):
            value = raw.get(field)
            if cls._valid_dns_label(value):
                result[field] = value

        return result
