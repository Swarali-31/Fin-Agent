"""Typed state, plans, traces, and final results for the master workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.common import AgentEnvelope, ApiError

AgentId = Literal[
    "expense_analysis",
    "budget_planning",
    "financial_research",
    "financial_report",
]
StepStatus = Literal[
    "pending",
    "running",
    "success",
    "partial",
    "failed",
    "skipped_dependency_failed",
    "invalidated",
]
TraceType = Literal[
    "plan",
    "route",
    "agent_call",
    "agent_result",
    "validation",
    "retry",
    "replan",
    "skip",
    "error",
    "final",
]


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agent: AgentId
    depends_on: list[str] = Field(default_factory=list)
    input_refs: dict[str, str] = Field(default_factory=dict)
    status: StepStatus = "pending"
    attempts: int = Field(default=0, ge=0)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[PlanStep]
    source: Literal["llm", "deterministic_fallback"]


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int = Field(..., ge=1)
    timestamp: datetime
    type: TraceType
    step_id: str | None = None
    agent: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0)


class ProvenanceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    step_id: str
    version: str | None = None
    field_path: str
    value: Any


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    context: dict[str, Any] = Field(default_factory=dict)
    plan: ExecutionPlan | None = None
    results: dict[str, AgentEnvelope] = Field(default_factory=dict)
    trace_events: list[TraceEvent] = Field(default_factory=list)
    replan_count: int = Field(default=0, ge=0)
    errors: list[ApiError] = Field(default_factory=list)
    final_answer: str | None = None
    claims: list[ProvenanceClaim] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    workflow_run_id: str | None = None
    terminated: bool = False


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "partial", "failed"]
    task: str
    plan: ExecutionPlan | None = None
    results: dict[str, AgentEnvelope] = Field(default_factory=dict)
    trace_events: list[TraceEvent] = Field(default_factory=list)
    replan_count: int = 0
    errors: list[ApiError] = Field(default_factory=list)
    final_answer: str
    claims: list[ProvenanceClaim] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
