from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

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
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PromptInput(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


class DeploymentPlanInput(BaseModel):
    destination: Literal["gamgee", "own_cloud"]
    service_model: Literal["iaas", "paas", "hybrid"]
    vm_count: int = Field(ge=1, le=10000)
    vcpu_per_vm: int = Field(default=2, ge=1, le=256)
    memory_gb_per_vm: int = Field(default=4, ge=1, le=4096)
