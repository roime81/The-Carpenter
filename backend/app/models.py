from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentHeartbeat(BaseModel):
    node_id: str = Field(min_length=8, max_length=128)
    hostname: str = Field(min_length=1, max_length=255)
    operating_system: str = Field(min_length=1, max_length=160)
    architecture: str = Field(min_length=1, max_length=80)
    cpu_cores: int = Field(ge=1, le=4096)
    memory_total_bytes: int = Field(ge=0)
    memory_available_bytes: int = Field(ge=0)
    disk_total_bytes: int = Field(ge=0)
    disk_free_bytes: int = Field(ge=0)
    ipv4_addresses: list[str] = Field(default_factory=list, max_length=32)
    capabilities: dict[str, str] = Field(default_factory=dict, max_length=128)
    discovery: dict[str, Any] = Field(default_factory=dict)
    failure_domain: str = Field(default="default", max_length=128)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobEnqueueRequest(BaseModel):
    function_name: str = Field(min_length=3, max_length=160)
    function_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)
    priority: int = Field(default=100, ge=0, le=1000)
    idempotency_key: str | None = Field(default=None, max_length=256)
    target_worker_id: str | None = Field(default=None, max_length=128)


class JobResultRequest(BaseModel):
    lease_token: str = Field(min_length=16, max_length=128)
    result: dict[str, Any] = Field(default_factory=dict)


class JobFailureRequest(BaseModel):
    lease_token: str = Field(min_length=16, max_length=128)
    error: str = Field(min_length=1, max_length=4000)


class DeploymentPlanInput(BaseModel):
    destination: Literal["gamgee", "own_cloud"]
    service_model: Literal["iaas", "paas", "hybrid"]
    vm_count: int = Field(ge=1, le=10000)
    vcpu_per_vm: int = Field(default=2, ge=1, le=256)
    memory_gb_per_vm: int = Field(default=4, ge=1, le=4096)
    disk_gb_per_vm: int = Field(default=40, ge=1, le=100000)
    high_availability: bool = False
