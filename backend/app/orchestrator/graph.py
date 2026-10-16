"""LangGraph master workflow with bounded execution, validation, and replanning."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from typing import Any, TypedDict

from fastapi.encoders import jsonable_encoder
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, ConfigDict

from backend.app.config.settings import Settings, get_settings
from backend.app.repositories.base import PersistenceNotConfigured, Repository
from backend.app.repositories.postgres import get_repository
from backend.app.schemas.common import AgentEnvelope, AgentProvenance, ApiError
from backend.app.services.adapters.base import AgentAdapter
from backend.app.services.adapters.budget_planning import BudgetPlanningAdapter
from backend.app.services.adapters.expense_analysis import ExpenseAnalysisAdapter
from backend.app.services.adapters.financial_report import FinancialReportAdapter
from backend.app.services.adapters.financial_research import FinancialResearchAdapter
from backend.app.orchestrator.planning import (
    InvalidPlan,
    MissingWorkflowInput,
    ProposedPlan,
    deterministic_plan,
    plan_prompt,
    validate_plan,
)
from backend.app.orchestrator.schemas import (
    PlanStep,
    ProvenanceClaim,
    TraceEvent,
    WorkflowResult,
    WorkflowState,
)


class _GraphState(TypedDict, total=False):
    workflow: WorkflowState


class _Narrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str


class _Runtime:
    def __init__(
        self,
        *,
        adapters: dict[str, AgentAdapter],
        llm: Any,
        repository: Repository | None,
        settings: Settings,
    ) -> None:
        self.adapters = adapters
        self.llm = llm
        self.repository = repository
        self.settings = settings
        self.workflow_run_id: str | None = None
        self.persistence_error: str | None = None

    def planner_llm(self, state: WorkflowState) -> Any:
        if self.llm is not None:
            return self.llm
        if "llm" in state.context:
            return state.context["llm"]
        for adapter in self.adapters.values():
            resolver = getattr(adapter, "resolve_llm", None)
            if resolver is not None:
                return resolver(state.context)
        return None

    def record(
        self,
        state: WorkflowState,
        event_type: str,
        summary: str,
        *,
        step_id: str | None = None,
        agent: str | None = None,
        details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        event = TraceEvent(
            seq=len(state.trace_events) + 1,
            timestamp=datetime.now(UTC),
            type=event_type,  # type: ignore[arg-type]
            step_id=step_id,
            agent=agent,
            summary=summary,
            details=details or {},
            duration_ms=duration_ms,
        )
        state.trace_events.append(event)
        if self.repository is not None and self.workflow_run_id is not None:
            try:
                self.repository.add_trace_event(
                    self.workflow_run_id,
                    event_type=event.type,
                    payload=event.model_dump(mode="json"),
                    agent=event.agent,
                )
            except Exception as exc:
                self.persistence_error = (
                    f"Could not persist trace event {event.seq}: {type(exc).__name__}"
                )

    def agent_context(self, state: WorkflowState) -> dict[str, Any]:
        result = dict(state.context)
        if self.llm is not None:
            result["llm"] = self.llm
        return result


def build_workflow_graph(
    *,
    adapters: dict[str, AgentAdapter] | None = None,
    llm: Any = None,
    repository: Repository | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build the reusable LangGraph state machine for specialist workflows."""
    runtime = _Runtime(
        adapters=adapters or _default_adapters(),
        llm=llm,
        repository=repository,
        settings=settings or get_settings(),
    )
    return _create_graph(runtime)


def _create_graph(runtime: _Runtime) -> Any:
    graph = StateGraph(_GraphState)

    async def plan_node(raw_state: _GraphState) -> _GraphState:
        state = raw_state["workflow"]
        try:
            planner_llm = runtime.planner_llm(state)
            if planner_llm is None or planner_llm is False:
                state.plan = deterministic_plan(state.task, state.context)
                runtime.record(
                    state,
                    "plan",
                    "A deterministic fallback plan was selected.",
                    details={"planner": "deterministic_fallback"},
                )
            else:
                proposal = await _get_proposed_plan(planner_llm, state)
                state.plan = validate_plan(
                    proposal,
                    state.context,
                    source="llm",
                    max_steps=runtime.settings.max_steps,
                )
                runtime.record(
                    state,
                    "plan",
                    "The structured LLM plan passed validation.",
                    details={"planner": "llm", "step_count": len(state.plan.steps)},
                )
        except MissingWorkflowInput as exc:
            _workflow_error(state, exc.code, str(exc), exc.details)
            runtime.record(state, "error", str(exc), details={"code": exc.code, **exc.details})
            state.terminated = True
        except InvalidPlan as exc:
            _workflow_error(state, exc.code, str(exc), exc.details)
            runtime.record(state, "error", str(exc), details={"code": exc.code, **exc.details})
            state.terminated = True
        except Exception as exc:
            # A planner invocation failure uses the existing real-agent fallback.
            runtime.record(state, "validation", "AI planning was unavailable; preparing a standard specialist route.", details={"planner_error_type": type(exc).__name__, "provider_status": str(getattr(exc, "code", getattr(exc, "status_code", "")))})
            try:
                state.plan = deterministic_plan(state.task, state.context)
                runtime.record(
                    state,
                    "plan",
                    "Planner invocation failed; deterministic fallback selected.",
                    details={
                        "planner": "deterministic_fallback",
                        "reason": type(exc).__name__,
                    },
                )
            except InvalidPlan as fallback_exc:
                _workflow_error(
                    state,
                    fallback_exc.code,
                    str(fallback_exc),
                    fallback_exc.details,
                )
                runtime.record(
                    state,
                    "error",
                    str(fallback_exc),
                    details={"code": fallback_exc.code, **fallback_exc.details},
                )
                state.terminated = True
        if state.plan is not None and len(state.plan.steps) > runtime.settings.max_steps:
            _workflow_error(
                state,
                "max_steps_exceeded",
                f"Workflow exceeds MAX_STEPS={runtime.settings.max_steps}.",
                {"max_steps": runtime.settings.max_steps},
            )
            state.terminated = True
        return {"workflow": state}

    async def execute_node(raw_state: _GraphState) -> _GraphState:
        state = raw_state["workflow"]
        if state.terminated or state.plan is None:
            return {"workflow": state}
        steps = state.plan.steps
        by_id = {step.id: step for step in steps}
        failed_dependency = False
        for step in steps:
            if step.status != "pending":
                continue
            failed_dependencies = [
                dep
                for dep in step.depends_on
                if by_id[dep].status in {"failed", "skipped_dependency_failed"}
                and not (
                    step.agent == "financial_report"
                    and by_id[dep].agent == "financial_research"
                )
            ]
            if failed_dependencies:
                step.status = "skipped_dependency_failed"
                failed_dependency = True
                runtime.record(
                    state,
                    "skip",
                    "Step skipped because a dependency failed.",
                    step_id=step.id,
                    agent=step.agent,
                    details={"failed_dependencies": failed_dependencies},
                )
        if failed_dependency:
            return {"workflow": state}

        ready = [
            step
            for step in steps
            if step.status == "pending"
            and all(
                by_id[dep].status in {"success", "partial"}
                or (
                    step.agent == "financial_report"
                    and by_id[dep].agent == "financial_research"
                    and by_id[dep].status in {"failed", "skipped_dependency_failed"}
                )
                for dep in step.depends_on
            )
        ]
        if not ready:
            return {"workflow": state}
        await asyncio.gather(*(_run_step(step, state, runtime) for step in ready))
        return {"workflow": state}

    async def validate_node(raw_state: _GraphState) -> _GraphState:
        state = raw_state["workflow"]
        if state.terminated or state.plan is None:
            return {"workflow": state}
        stale_steps: list[PlanStep] = []
        by_id = {step.id: step for step in state.plan.steps}
        for step in state.plan.steps:
            if step.status not in {"success", "partial"}:
                continue
            error = _validate_envelope(step, state.results.get(step.id), state, by_id)
            if error is not None:
                runtime.record(
                    state,
                    "validation",
                    error["message"],
                    step_id=step.id,
                    agent=step.agent,
                    details=error,
                )
                if error["code"] == "stale_version":
                    stale_steps.append(step)
                else:
                    step.status = "failed"
                    _workflow_error(state, error["code"], error["message"], error)

        if stale_steps:
            state.replan_count += 1
            if state.replan_count > runtime.settings.max_replans:
                _workflow_error(
                    state,
                    "max_replans_exceeded",
                    f"Workflow exceeded MAX_REPLANS={runtime.settings.max_replans}.",
                    {"max_replans": runtime.settings.max_replans},
                )
                state.terminated = True
            else:
                stale_ids = {step.id for step in stale_steps}
                invalidated = _dependent_closure(state.plan.steps, stale_ids)
                for invalid_id in invalidated:
                    step = by_id[invalid_id]
                    if step.agent == "expense_analysis":
                        continue
                    step.status = "pending"
                runtime.record(
                    state,
                    "replan",
                    "Stale upstream versions invalidated dependent steps.",
                    details={
                        "stale_steps": sorted(stale_ids),
                        "invalidated_steps": sorted(invalidated),
                        "replan_count": state.replan_count,
                    },
                )
        return {"workflow": state}

    def route_node(raw_state: _GraphState) -> _GraphState:
        state = raw_state["workflow"]
        if not state.terminated and state.plan is not None:
            runtime.record(
                state,
                "route",
                "Workflow execution state evaluated.",
                details={
                    "pending": [
                        step.id for step in state.plan.steps if step.status == "pending"
                    ],
                    "replan_count": state.replan_count,
                },
            )
        return {"workflow": state}

    async def synthesize_node(raw_state: _GraphState) -> _GraphState:
        state = raw_state["workflow"]
        await _synthesize(state, runtime)
        runtime.record(
            state,
            "final",
            "Workflow result assembled from specialist outputs.",
            details={"status": _workflow_status(state)},
        )
        if runtime.repository is not None and runtime.workflow_run_id is not None:
            try:
                runtime.repository.finish_workflow_run(
                    runtime.workflow_run_id,
                    status=_workflow_status(state),
                    result_data=_result_payload(state),
                    finished_at=datetime.now(UTC),
                )
            except Exception as exc:
                state.errors.append(
                    ApiError(
                        code="persistence_error",
                        message="Workflow completed but could not be persisted.",
                        details={"exception_type": type(exc).__name__},
                    )
                )
        if runtime.persistence_error:
            state.errors.append(
                ApiError(
                    code="trace_persistence_error",
                    message="Workflow completed but one or more persistence operations failed.",
                    details={"reason": runtime.persistence_error},
                )
            )
        return {"workflow": state}

    graph.add_node("plan", plan_node)
    graph.add_node("execute_step", execute_node)
    graph.add_node("validate", validate_node)
    graph.add_node("route", route_node)
    graph.add_node("synthesize", synthesize_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute_step")
    graph.add_edge("execute_step", "validate")
    graph.add_edge("validate", "route")
    graph.add_conditional_edges(
        "route",
        lambda raw_state: _next_node(raw_state["workflow"]),
        {"execute_step": "execute_step", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)
    return graph.compile()


async def run_workflow(
    task: str,
    context: dict[str, Any] | None = None,
    *,
    llm: Any = None,
    adapters: dict[str, AgentAdapter] | None = None,
    repository: Repository | None = None,
    settings: Settings | None = None,
) -> WorkflowResult:
    """Run a workflow and return actual specialist results and append-only trace."""
    normalized_context = _normalize_context(context or {})
    chosen_settings = settings or get_settings()
    resolved_repository = repository
    if resolved_repository is None and chosen_settings.database_url:
        try:
            resolved_repository = get_repository(settings=chosen_settings)
        except PersistenceNotConfigured:
            resolved_repository = None

    runtime = _Runtime(
        adapters=adapters or _default_adapters(chosen_settings),
        llm=llm,
        repository=resolved_repository,
        settings=chosen_settings,
    )
    state = WorkflowState(task=task, context=normalized_context)
    if resolved_repository is not None:
        try:
            runtime.workflow_run_id = resolved_repository.create_workflow_run(
                input_data={"task": task, "context": _json_safe(normalized_context)},
                started_at=datetime.now(UTC),
                profile_id=_profile_id(normalized_context),
            )
            state.workflow_run_id = runtime.workflow_run_id
        except Exception as exc:
            runtime.persistence_error = f"Could not create workflow run: {type(exc).__name__}"

    graph = _create_graph(runtime)
    final_state = (await graph.ainvoke({"workflow": state}))["workflow"]
    return WorkflowResult(
        status=_workflow_status(final_state),
        task=final_state.task,
        plan=final_state.plan,
        results=final_state.results,
        trace_events=final_state.trace_events,
        replan_count=final_state.replan_count,
        errors=final_state.errors,
        final_answer=final_state.final_answer or "No specialist result was produced.",
        claims=final_state.claims,
        sources=final_state.sources,
    )


def _default_adapters(settings: Settings | None = None) -> dict[str, AgentAdapter]:
    return {
        "expense_analysis": ExpenseAnalysisAdapter(settings),
        "budget_planning": BudgetPlanningAdapter(settings),
        "financial_research": FinancialResearchAdapter(settings),
        "financial_report": FinancialReportAdapter(settings),
    }


async def _get_proposed_plan(llm: Any, state: WorkflowState) -> ProposedPlan:
    structured = llm.with_structured_output(ProposedPlan)
    response = await _maybe_await(structured.ainvoke(plan_prompt(state.task, state.context)))
    proposal = response if isinstance(response, ProposedPlan) else ProposedPlan.model_validate(response)
    # Literal questions are a model formatting error, never an executable path.
    # Bind them to the actual user task, then run every existing plan validator.
    for step in proposal.steps:
        if step.agent == "financial_research":
            reference = step.input_refs.get("question", "")
            if reference and reference != "task" and not reference.startswith(("context.", "result.")):
                step.input_refs["question"] = "task"
    return proposal


async def _run_step(step: PlanStep, state: WorkflowState, runtime: _Runtime) -> None:
    adapter = runtime.adapters.get(step.agent)
    if adapter is None:
        step.status = "failed"
        _workflow_error(
            state,
            "agent_not_available",
            f"No adapter is registered for {step.agent}.",
            {"agent": step.agent},
        )
        runtime.record(
            state,
            "error",
            f"No adapter is registered for {step.agent}.",
            step_id=step.id,
            agent=step.agent,
        )
        return

    call_input = _resolve_step_input(step, state)
    context = runtime.agent_context(state)
    started = time.perf_counter()
    step.status = "running"
    cached = state.context.get("cached_expense_analysis") if step.agent == "expense_analysis" and "analy" not in state.task.lower() else None
    if cached:
        try:
            from finagent.schemas.expense import ExpenseAnalysisResult
            from finagent.schemas.financial import FinancialProfile
            from finagent.agents.expense_analysis.calculations import compute_expense_metrics
            validated = ExpenseAnalysisResult.model_validate(cached)
            metrics = compute_expense_metrics(FinancialProfile.model_validate(call_input["profile"]))
            if validated.status.value != "success" or validated.analysis_version != metrics.analysis_version:
                cached = None
        except Exception:
            cached = None
    while True:
        step.attempts += 1
        runtime.record(
            state,
            "validation" if cached else "agent_call",
            "Using your saved analysis; its transactions are unchanged." if cached else "Calling specialist adapter.",
            step_id=step.id,
            agent=step.agent,
            details={"attempt": step.attempts},
        )
        try:
            existing = state.results.get(step.id)
            if cached:
                envelope = AgentEnvelope(agent=step.agent, status=validated.status.value, result=validated.model_dump(mode="json"), provenance=AgentProvenance(agent=step.agent, analysis_version=validated.analysis_version, input_hash=hashlib.sha256(json.dumps(_json_safe(call_input), sort_keys=True).encode()).hexdigest(), started_at=datetime.now(UTC), duration_ms=0))
            elif (
                step.agent == "budget_planning"
                and existing is not None
                and existing.result is not None
                and "expense_analysis" in call_input
                and hasattr(adapter, "revise")
            ):
                envelope = await adapter.revise(
                    existing.result,
                    call_input["expense_analysis"],
                    context,
                )
            else:
                envelope = await adapter.run(call_input, context)
        except Exception as exc:
            envelope = _unexpected_adapter_failure(step.agent, call_input, exc)
        state.results[step.id] = envelope
        retryable = _is_retryable(envelope)
        if envelope.status != "failed" or not retryable:
            break
        if step.attempts > runtime.settings.max_retries_per_step:
            break
        step.status = "pending"
        runtime.record(
            state,
            "retry",
            "Retrying a failed specialist call.",
            step_id=step.id,
            agent=step.agent,
            details={
                "attempt": step.attempts,
                "max_retries": runtime.settings.max_retries_per_step,
            },
        )
        delay = runtime.settings.retry_backoff_seconds * (2 ** (step.attempts - 1))
        if delay:
            await asyncio.sleep(delay)

    step.status = envelope.status
    runtime.record(
        state,
        "agent_result",
        f"Specialist returned {envelope.status}.",
        step_id=step.id,
        agent=step.agent,
        details={"errors": envelope.errors, "limitations": envelope.limitations},
        duration_ms=max(0, int((time.perf_counter() - started) * 1000)),
    )
    if envelope.status == "failed":
        errors = envelope.errors or [
            {"code": "agent_failed", "message": f"{step.agent} returned failed status."}
        ]
        for error in errors:
            state.errors.append(
                ApiError(
                    code=str(error.get("code", "agent_failed")),
                    message=str(error.get("message", f"{step.agent} failed.")),
                    details={
                        "agent": step.agent,
                        "step_id": step.id,
                        **(
                            error.get("details", {})
                            if isinstance(error.get("details"), dict)
                            else {}
                        ),
                    },
                )
            )


def _resolve_step_input(step: PlanStep, state: WorkflowState) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, reference in step.input_refs.items():
        if reference == "task":
            resolved[key] = state.context.get("research_question", state.task)
        elif reference.startswith("context."):
            resolved[key] = _path(state.context, reference.removeprefix("context."))
        elif reference.startswith("result."):
            remainder = reference.removeprefix("result.")
            source_id, *parts = remainder.split(".")
            if source_id not in state.results or state.results[source_id].result is None:
                continue
            envelope = state.results[source_id]
            value: Any = envelope.result
            for part in parts:
                value = value[part]
            resolved[key] = value
    if step.agent == "expense_analysis" and "profile" not in resolved:
        if state.context.get("transactions"):
            resolved["profile"] = {
                "profile_id": state.context["profile_id"],
                "currency": state.context.get("currency", "INR"),
                "transactions": state.context["transactions"],
                "savings_goal": state.context.get("savings_goal"),
            }
    elif step.agent == "financial_research":
        resolved["question"] = resolved.get("question", state.task)
    elif step.agent == "budget_planning":
        resolved.update(
            {
                key: state.context[key]
                for key in ("savings_goal", "essential_categories", "currency")
                if key in state.context
            }
        )
    elif step.agent == "financial_report":
        if "budget" in resolved:
            resolved["budget"] = resolved.pop("budget")
    return resolved


def _validate_envelope(
    step: PlanStep,
    envelope: AgentEnvelope | None,
    state: WorkflowState,
    by_id: dict[str, PlanStep],
) -> dict[str, Any] | None:
    if envelope is None or envelope.agent != step.agent or envelope.result is None:
        return {
            "code": "invalid_agent_envelope",
            "message": f"{step.agent} returned an incomplete or mismatched envelope.",
        }
    payload = envelope.result
    payload_status = payload.get("status")
    if payload_status not in {"success", "partial", "failed"}:
        return {
            "code": "invalid_agent_result",
            "message": f"{step.agent} result has a missing or invalid status.",
            "actual_status": payload_status,
        }
    if payload_status != envelope.status:
        return {
            "code": "invalid_agent_envelope",
            "message": f"{step.agent} envelope status does not match its result status.",
            "envelope_status": envelope.status,
            "result_status": payload_status,
        }
    if envelope.status == "failed":
        return None

    required_fields = {
        "expense_analysis": ("summary",),
        "budget_planning": (
            "currency",
            "monthly_income",
            "category_limits",
            "planned_monthly_savings",
            "feasibility",
        ),
        "financial_research": ("question", "findings", "sources"),
        "financial_report": ("validation_status", "validation_summary"),
    }.get(step.agent, ())
    required_versions = {
        "expense_analysis": ("analysis_version",),
        "budget_planning": ("budget_id", "source_analysis_version"),
        "financial_report": ("report_version", "source_versions"),
    }.get(step.agent, ())
    missing = [
        field
        for field in (*required_fields, *required_versions)
        if field not in payload or payload[field] is None
    ]
    if missing:
        return {
            "code": "invalid_agent_result",
            "message": f"{step.agent} result is missing required fields.",
            "missing": missing,
        }
    required_mappings = {
        "expense_analysis": ("summary",),
        "budget_planning": ("monthly_income", "planned_monthly_savings", "feasibility"),
        "financial_report": ("source_versions",),
    }.get(step.agent, ())
    invalid_mappings = [
        field
        for field in required_mappings
        if not isinstance(payload.get(field), dict)
    ]
    if invalid_mappings:
        return {
            "code": "invalid_agent_result",
            "message": f"{step.agent} result has invalid object fields.",
            "invalid_fields": invalid_mappings,
        }
    invalid_collections = [
        field
        for field in ("category_limits", "findings", "sources")
        if field in required_fields and not isinstance(payload.get(field), list)
    ]
    if invalid_collections:
        return {
            "code": "invalid_agent_result",
            "message": f"{step.agent} result has invalid collection fields.",
            "invalid_fields": invalid_collections,
        }
    dependencies = {
        by_id[dependency].agent: state.results.get(dependency)
        for dependency in step.depends_on
    }
    if step.agent == "budget_planning":
        expense = dependencies.get("expense_analysis")
        if expense and expense.result:
            current_version = expense.result.get("analysis_version")
            if payload.get("source_analysis_version") != current_version:
                return {
                    "code": "stale_version",
                    "message": "Budget source_analysis_version differs from the current expense analysis.",
                    "expected": current_version,
                    "actual": payload.get("source_analysis_version"),
                }
    elif step.agent == "financial_report":
        expense = dependencies.get("expense_analysis")
        budget = dependencies.get("budget_planning")
        sources = payload.get("source_versions") or {}
        if expense and expense.result and sources.get("analysis_version") != expense.result.get("analysis_version"):
            return {
                "code": "stale_version",
                "message": "Report analysis_version differs from the current expense analysis.",
                "expected": expense.result.get("analysis_version"),
                "actual": sources.get("analysis_version"),
            }
        if budget and budget.result and (
            sources.get("budget_id") != budget.result.get("budget_id")
            or sources.get("budget_revision") != budget.result.get("revision")
        ):
            return {
                "code": "stale_version",
                "message": "Report budget version differs from the current budget.",
                "expected_budget_id": budget.result.get("budget_id"),
                "actual_budget_id": sources.get("budget_id"),
                "expected_revision": budget.result.get("revision"),
                "actual_revision": sources.get("budget_revision"),
            }
    return None


def _dependent_closure(steps: list[PlanStep], roots: set[str]) -> set[str]:
    closure = set(roots)
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step.id not in closure and set(step.depends_on) & closure:
                closure.add(step.id)
                changed = True
    return closure


def _next_node(state: WorkflowState) -> str:
    if state.terminated or state.plan is None:
        return "synthesize"
    if any(step.status in {"pending", "running"} for step in state.plan.steps):
        # A pending step may be blocked by a failed dependency; execute_step
        # marks these as skipped before selecting ready work.
        return "execute_step"
    return "synthesize"


async def _synthesize(state: WorkflowState, runtime: _Runtime) -> None:
    if state.plan is None:
        state.final_answer = "The workflow could not produce a valid execution plan."
        return
    claims: list[ProvenanceClaim] = []
    sources: list[dict[str, Any]] = []
    for step in state.plan.steps:
        envelope = state.results.get(step.id)
        if (
            envelope is None
            or envelope.result is None
            or envelope.status == "failed"
            or step.status in {"failed", "skipped_dependency_failed"}
        ):
            continue
        for path in _claim_paths(step.agent, envelope.result):
            value = _path(envelope.result, path)
            if value is None:
                continue
            claims.append(
                ProvenanceClaim(
                    agent=step.agent,
                    step_id=step.id,
                    version=_version(envelope),
                    field_path=path,
                    value=value,
                )
            )
        if step.agent == "financial_research":
            sources.extend(envelope.result.get("sources", []))

    deterministic = _deterministic_summary(state, claims)
    narrative_llm = runtime.planner_llm(state)
    if narrative_llm is not None and narrative_llm is not False and claims:
        try:
            structured = narrative_llm.with_structured_output(_Narrative)
            response = await _maybe_await(
                structured.ainvoke(
                    json.dumps(
                        {
                            "task": state.task,
                            "verified_values": [claim.value for claim in claims],
                            "verified_sources": sources,
                        },
                        default=str,
                    )
                )
            )
            narrative = response if isinstance(response, _Narrative) else _Narrative.model_validate(response)
            if narrative_is_grounded(narrative.summary, state.results):
                state.final_answer = narrative.summary
            else:
                state.final_answer = deterministic + " (deterministic fallback; ungrounded narrative rejected)"
                runtime.record(
                    state,
                    "validation",
                    "Narrative contained a number or URL absent from specialist outputs.",
                    details={"fallback": "deterministic"},
                )
        except Exception as exc:
            state.final_answer = deterministic + " (deterministic fallback; narrative unavailable)"
            runtime.record(
                state,
                "validation",
                "Narrative synthesis failed; deterministic fallback used.",
                details={"exception_type": type(exc).__name__},
            )
    else:
        state.final_answer = deterministic
    state.claims = claims
    state.sources = sources


def narrative_is_grounded(text: str, results: dict[str, AgentEnvelope]) -> bool:
    """Reject narrative numbers and URLs that are not in actual agent outputs."""
    serialized = json.dumps(
        {key: envelope.result for key, envelope in results.items()},
        sort_keys=True,
        default=str,
    )
    output_numbers = set(re.findall(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?", serialized))
    narrative_numbers = set(re.findall(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?", text))
    output_urls = set(re.findall(r"https?://[^\s\"'<>]+", serialized))
    narrative_urls = set(re.findall(r"https?://[^\s\"'<>]+", text))
    output_urls = {url.rstrip(".,;:!?") for url in output_urls}
    narrative_urls = {url.rstrip(".,;:!?") for url in narrative_urls}
    return narrative_numbers.issubset(output_numbers) and narrative_urls.issubset(output_urls)


def _claim_paths(agent: str, result: dict[str, Any]) -> list[str]:
    summary = result.get("summary") or {}
    sections = result.get("sections") or {}
    category_totals = summary.get("category_totals") or {}
    paths = list({
        "expense_analysis": [
            "summary.monthly_income.amount",
            "summary.monthly_expenses.amount",
            "summary.available_surplus.amount",
            *(
                f"summary.category_totals.{category}.amount"
                for category in category_totals
            ),
        ],
        "budget_planning": [
            "monthly_income.amount",
            "planned_monthly_savings.amount",
            "feasibility.is_feasible",
            "feasibility.requested_monthly_savings.amount",
            "feasibility.max_achievable_monthly_savings.amount",
            "feasibility.shortfall.amount",
            *(
                f"category_limits.{index}.{field}"
                for index, _ in enumerate(result.get("category_limits", []))
                for field in ("category", "monthly_limit.amount")
            ),
        ],
        "financial_research": [
            *(
                f"findings.{index}.{field}"
                for index, _ in enumerate(result.get("findings", []))
                for field in ("statement", "source_ids")
            ),
            *(
                f"sources.{index}.{field}"
                for index, _ in enumerate(result.get("sources", []))
                for field in ("title", "url")
            ),
        ],
        "financial_report": [
            "validation_status",
            "validation_summary",
            "sections.summary",
            *(
                f"sections.{section}.{index}"
                for section in (
                    "spending_insights",
                    "savings_opportunities",
                    "risk_considerations",
                )
                for index, _ in enumerate(sections.get(section, []))
            ),
        ],
    }.get(agent, []))
    return [path for path in paths if _path(result, path) is not None]


def _deterministic_summary(state: WorkflowState, claims: list[ProvenanceClaim]) -> str:
    if not claims:
        statuses = ", ".join(
            f"{step.agent}: {state.results[step.id].status}"
            for step in (state.plan.steps if state.plan else [])
            if step.id in state.results
        )
        return f"No verified financial claims were produced. Specialist statuses: {statuses or 'none'}."
    sentences = []
    for step in state.plan.steps if state.plan else []:
        envelope = state.results.get(step.id)
        if not envelope or envelope.result is None or envelope.status == "failed":
            sentences.append(f"{step.agent.replace('_', ' ').title()} could not finish. See the execution trace for the reason.")
            continue
        result = envelope.result
        def amount(value):
            return (value or {}).get("amount", "unavailable")
        if step.agent == "expense_analysis":
            summary = result.get("summary") or {}
            sentences.append(f"Your monthly income is {amount(summary.get('monthly_income'))} {summary.get('currency', '')}. Your monthly expenses are {amount(summary.get('monthly_expenses'))}.")
        elif step.agent == "budget_planning":
            sentences.append(f"Your budget sets aside {amount(result.get('planned_monthly_savings'))} {result.get('currency', '')} each month. " + ("The savings target fits within your income." if result.get('feasibility', {}).get('is_feasible') else "The requested savings target needs changes; review the budget suggestions."))
        elif step.agent == "financial_research":
            findings = result.get("findings") or []
            sentences.extend(str(item.get("statement", "")) for item in findings[:3])
            sentences.append(f"Research returned {len(result.get('sources', []))} sources. Open the source links to read the evidence.")
        elif step.agent == "financial_report":
            sentences.append("Your report is ready in Reports. " + ("It includes warnings about missing information; review them before using it." if result.get("validation_status") == "flagged" else "The available inputs passed the report checks."))
        if envelope.status == "partial" and step.agent != "financial_report":
            sentences.append("Some information or features were unavailable. The results show only what could be verified.")
    return "\n\n".join(sentences)



def _workflow_status(state: WorkflowState) -> str:
    statuses = [envelope.status for envelope in state.results.values()]
    if state.errors and not statuses:
        return "failed"
    if any(status == "failed" for status in statuses) or state.errors:
        return "partial" if any(status in {"success", "partial"} for status in statuses) else "failed"
    if not statuses:
        return "failed"
    if any(status == "partial" for status in statuses):
        return "partial"
    if state.plan and any(
        step.status == "skipped_dependency_failed" for step in state.plan.steps
    ):
        return "partial"
    return "success"


def _is_retryable(envelope: AgentEnvelope) -> bool:
    if envelope.status != "failed":
        return False
    non_retryable = {
        "invalid_input",
        "validation_error",
        "misconfigured",
        "search_not_configured",
        "persistence_not_configured",
        "invalid_agent_result",
        "invalid_agent_envelope",
    }
    codes = {str(error.get("code", "")).lower() for error in envelope.errors}
    return not codes.intersection(non_retryable)


def _unexpected_adapter_failure(agent: str, input_value: Any, exc: Exception) -> AgentEnvelope:
    now = datetime.now(UTC)
    input_hash = hashlib.sha256(
        json.dumps(_json_safe(input_value), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return AgentEnvelope(
        agent=agent,
        status="failed",
        result=None,
        errors=[
            {
                "code": "adapter_execution_error",
                "message": "The specialist adapter raised an unexpected execution error.",
                "details": {"exception_type": type(exc).__name__},
            }
        ],
        provenance=AgentProvenance(
            agent=agent,
            input_hash=input_hash,
            started_at=now,
            duration_ms=0,
        ),
    )


def _workflow_error(
    state: WorkflowState,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    state.errors.append(ApiError(code=code, message=message, details=details or None))


def _normalize_context(context: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(context)
    if "profile" not in normalized and normalized.get("transactions") and normalized.get("profile_id"):
        normalized["profile"] = {
            "profile_id": normalized["profile_id"],
            "currency": normalized.get("currency", "INR"),
            "transactions": normalized["transactions"],
            "savings_goal": normalized.get("savings_goal"),
        }
    return normalized


def _profile_id(context: dict[str, Any]) -> str | None:
    profile = context.get("profile")
    if isinstance(profile, dict):
        return profile.get("profile_id")
    return getattr(profile, "profile_id", None)


def _path(value: Any, path: str) -> Any:
    result = value
    for part in path.split("."):
        if isinstance(result, list) and part.isdecimal():
            index = int(part)
            result = result[index] if index < len(result) else None
        elif isinstance(result, dict):
            result = result.get(part)
        else:
            result = getattr(result, part, None)
        if result is None:
            return None
    return result


def _version(envelope: AgentEnvelope) -> str | None:
    provenance = envelope.provenance
    return (
        provenance.analysis_version
        or provenance.budget_id
        or provenance.report_version
        or provenance.source_analysis_version
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        value = {
            key: item
            for key, item in value.items()
            if key not in {"llm", "search_provider"}
        }
    return jsonable_encoder(value, custom_encoder={})


def _result_payload(state: WorkflowState) -> dict[str, Any]:
    return {
        "status": _workflow_status(state),
        "task": state.task,
        "plan": state.plan.model_dump(mode="json") if state.plan is not None else None,
        "results": {
            key: value.model_dump(mode="json") for key, value in state.results.items()
        },
        "trace_events": [
            event.model_dump(mode="json") for event in state.trace_events
        ],
        "replan_count": state.replan_count,
        "errors": [error.model_dump(mode="json") for error in state.errors],
        "final_answer": state.final_answer,
        "claims": [claim.model_dump(mode="json") for claim in state.claims],
        "sources": state.sources,
    }


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value
