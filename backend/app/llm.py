from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

logger = logging.getLogger("carpenter.llm")

SYSTEM_PROMPT = """You are the intent parser for The Carpenter, an infrastructure control plane.
Return JSON only with these optional keys:
vm_count (integer), destination ("gamgee" or "own_cloud"), service_model ("iaas", "paas", or "hybrid").
Only extract values the user explicitly stated. Never invent missing values. Do not output commands,
scripts, shell, function names, credentials, or infrastructure instructions. The backend validates
all extracted values and is the only component allowed to invoke registered functions."""


class ModelGateway:
    """Optional local/open-source or OpenAI-compatible intent extraction.

    The model only extracts constrained conversational slots. It cannot execute tools,
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
    def _validate(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        result: dict[str, Any] = {}
        count = raw.get("vm_count")
        if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 10000:
            result["vm_count"] = count
        destination = raw.get("destination")
        if destination in ("gamgee", "own_cloud"):
            result["destination"] = destination
        service_model = raw.get("service_model")
        if service_model in ("iaas", "paas", "hybrid"):
            result["service_model"] = service_model
        return result
