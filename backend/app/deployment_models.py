from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class DeploymentRequest(BaseModel):
    destination: Literal["gamgee", "own_cloud"]
    service_model: Literal["iaas", "paas", "hybrid"]
    vm_count: int = Field(ge=1, le=1000, description="VM count for IaaS, or desired replicas for PaaS.")
    vcpu_per_vm: int = Field(default=2, ge=1, le=256)
    memory_gb_per_vm: int = Field(default=4, ge=1, le=4096)
    disk_gb_per_vm: int = Field(default=40, ge=1, le=100000)
    high_availability: bool = False
    name: str = Field(default="carpenter-app", min_length=1, max_length=63)
    namespace: str = Field(default="default", min_length=1, max_length=63)
    container_image: str | None = Field(default=None, max_length=512)
    container_port: int = Field(default=8080, ge=1, le=65535)


class DeploymentApproval(BaseModel):
    approved_by: str = Field(min_length=1, max_length=128)
