from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable

logger = logging.getLogger("carpenter.faas")


@dataclass(frozen=True)
class FunctionDefinition:
    name: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    description: str
    timeout_seconds: float = 10.0


class FunctionRuntime:
    """Small, local Python-native FaaS runtime.

    Functions are allow-listed at registration and return structured dictionaries.
    The timeout bounds how long the caller waits; Python cannot forcibly terminate
    a handler already running in a thread. Only trusted, short-running functions
    belong in this MVP runtime. Production execution needs isolated worker processes
    or containers, durable queues and persistent idempotency.
    """

    def __init__(self, max_workers: int = 8) -> None:
        self._functions: dict[str, FunctionDefinition] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="carpenter-fn")
        self._idempotency: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = Lock()

    def register(self, definition: FunctionDefinition) -> None:
        if definition.name in self._functions:
            raise ValueError(f"Function already registered: {definition.name}")
        self._functions[definition.name] = definition

    def catalogue(self) -> list[dict[str, str]]:
        return [
            {"name": item.name, "description": item.description}
            for item in sorted(self._functions.values(), key=lambda value: value.name)
        ]

    def invoke(
        self,
        function_name: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        definition = self._functions.get(function_name)
        if definition is None:
            raise KeyError(f"Unknown or unregistered function: {function_name}")

        cache_key = (function_name, idempotency_key) if idempotency_key else None
        if cache_key:
            with self._lock:
                cached = self._idempotency.get(cache_key)
                if cached is not None:
                    return {**cached, "cached": True}

        invocation_id = str(uuid.uuid4())
        started = time.monotonic()
        future = self._pool.submit(definition.handler, payload)

        try:
            output = future.result(timeout=definition.timeout_seconds)
            if not isinstance(output, dict):
                raise TypeError("FaaS functions must return a dictionary")
            result = {
                "invocation_id": invocation_id,
                "function": function_name,
                "status": "succeeded",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "output": output,
                "cached": False,
            }
            if cache_key:
                with self._lock:
                    self._idempotency[cache_key] = result
            logger.info("FaaS invocation succeeded: %s (%s)", function_name, invocation_id)
            return result
        except FutureTimeout as exc:
            future.cancel()
            logger.warning("FaaS invocation timed out: %s (%s)", function_name, invocation_id)
            raise TimeoutError(
                f"Function '{function_name}' exceeded the caller wait limit; "
                "a running thread may continue until its handler returns"
            ) from exc
        except Exception:
            logger.exception("FaaS invocation failed: %s (%s)", function_name, invocation_id)
            raise

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
