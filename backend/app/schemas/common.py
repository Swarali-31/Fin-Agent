"""Stable API envelopes shared by backend routes and agent adapters."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] | None = None


class ResponseEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: Literal["ok", "error"]
    data: Any = None
    warnings: list[Any] = Field(default_factory=list)
    error: ApiError | None = None


class AgentProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    analysis_version: str | None = None
    budget_id: str | None = None
    budget_revision: int | None = None
    source_analysis_version: str | None = None
    report_version: str | None = None
    input_hash: str
    started_at: datetime
    duration_ms: int = Field(..., ge=0)


class AgentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    status: Literal["success", "partial", "failed"]
    result: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[dict[str, Any]] = Field(default_factory=list)
    provenance: AgentProvenance


class AdapterAvailability(str, Enum):
    """String values for adapter availability states."""

    available = "available"
    partial = "partial"
    not_implemented = "not_implemented"
    misconfigured = "misconfigured"


class AdapterStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AdapterAvailability
    missing: list[str] = Field(default_factory=list)
