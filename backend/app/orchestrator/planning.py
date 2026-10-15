"""Structured plan generation, deterministic fallback, and plan validation."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.orchestrator.schemas import ExecutionPlan, PlanStep


class ProposedStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agent: str
    depends_on: list[str] = Field(default_factory=list)
    input_refs: dict[str, str] = Field(default_factory=dict)


class ProposedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[ProposedStep] = Field(min_length=1)


class InvalidPlan(ValueError):
    """The proposed workflow is structurally invalid or lacks required inputs."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class MissingWorkflowInput(InvalidPlan):
    def __init__(self, missing: list[str]):
        super().__init__(
            "missing_input",
            "Required workflow inputs are missing.",
            {"missing": missing},
        )


_REF_PATTERN = re.compile(r"^(task|context\.[A-Za-z0-9_.-]+|result\.[A-Za-z0-9_.-]+)$")
_SUPPORTED_AGENTS = {
    "expense_analysis",
    "budget_planning",
    "financial_research",
    "financial_report",
}
def deterministic_plan(task: str, context: dict[str, Any]) -> ExecutionPlan:
    """Choose a minimal workflow from explicit task language and available inputs."""
    lowered = task.lower()
    research_requested = any(
        keyword in lowered for keyword in ("research", "education", "educational", "learn about")
    )
    report_requested = any(
        keyword in lowered for keyword in ("report", "financial summary")
    )
    budget_requested = any(
        keyword in lowered for keyword in ("budget", "savings plan", "savings target")
    )
    expense_requested = any(
        keyword in lowered
        for keyword in (
            "expense analysis",
            "analyze expenses",
            "analyze my expenses",
            "analyze my spending",
            "analyze spending",
            "spending analysis",
        )
    )

    # A report requires both financial upstream results. Research is included
    # only when it is explicitly part of the task.
    financial_requested = report_requested or budget_requested or expense_requested
    if not financial_requested and not research_requested:
        raise InvalidPlan(
            "task_not_supported",
            "The task does not identify a supported specialist capability.",
            {"supported_agents": sorted(_SUPPORTED_AGENTS)},
        )

    steps: list[PlanStep] = []
    if financial_requested:
        if not _has_profile_input(context):
            raise MissingWorkflowInput(["profile (profile_id, currency, and transactions)"])
        steps.append(
            PlanStep(
                id="expense_analysis",
                agent="expense_analysis",
                input_refs={"profile": "context.profile"},
            )
        )
        if report_requested or budget_requested:
            steps.append(
                PlanStep(
                    id="budget_planning",
                    agent="budget_planning",
                    depends_on=["expense_analysis"],
                    input_refs={
                        "expense_analysis": "result.expense_analysis",
                        **_optional_context_refs(
                            context,
                            ("savings_goal", "essential_categories", "currency"),
                        ),
                    },
                )
            )
        if report_requested:
            report_dependencies = ["expense_analysis", "budget_planning"]
            if research_requested:
                report_dependencies.append("financial_research")
            steps.append(
                PlanStep(
                    id="financial_report",
                    agent="financial_report",
                    depends_on=report_dependencies,
                    input_refs={
                        "expense_analysis": "result.expense_analysis",
                        "budget": "result.budget_planning",
                        **(
                            {"research": "result.financial_research"}
                            if research_requested
                            else {}
                        ),
                    },
                )
            )

    if research_requested:
        steps.append(
            PlanStep(
                id="financial_research",
                agent="financial_research",
                input_refs={"question": "task"},
            )
        )

    return validate_plan(
        ProposedPlan(
            steps=[
                ProposedStep(
                    id=step.id,
                    agent=step.agent,
                    depends_on=step.depends_on,
                    input_refs=step.input_refs,
                )
                for step in steps
            ]
        ),
        context,
        source="deterministic_fallback",
    )


def validate_plan(
    proposed: ProposedPlan | dict[str, Any],
    context: dict[str, Any],
    *,
    source: str,
    max_steps: int = 8,
) -> ExecutionPlan:
    try:
        parsed = proposed if isinstance(proposed, ProposedPlan) else ProposedPlan.model_validate(proposed)
    except ValidationError as exc:
        raise InvalidPlan(
            "invalid_plan",
            "The planner returned a plan that does not match the structured plan schema.",
            {"validation_errors": exc.errors(include_url=False)},
        ) from exc
    if len(parsed.steps) > max_steps:
        raise InvalidPlan(
            "max_steps_exceeded",
            f"The plan contains {len(parsed.steps)} steps; configured maximum is {max_steps}.",
            {"max_steps": max_steps, "step_count": len(parsed.steps)},
        )

    step_ids = [step.id for step in parsed.steps]
    if len(step_ids) != len(set(step_ids)) or any(not item.strip() for item in step_ids):
        raise InvalidPlan("invalid_plan", "Plan step IDs must be non-empty and unique.")

    by_id: dict[str, ProposedStep] = {step.id: step for step in parsed.steps}
    normalized_agents: dict[str, str] = {}
    for step in parsed.steps:
        if step.agent not in _SUPPORTED_AGENTS:
            raise InvalidPlan(
                "invalid_plan",
                f"Unknown agent {step.agent!r} in step {step.id!r}.",
                {"step_id": step.id, "agent": step.agent},
            )
        normalized_agents[step.id] = step.agent
        unknown_dependencies = set(step.depends_on) - set(by_id)
        if step.id in step.depends_on or unknown_dependencies:
            raise InvalidPlan(
                "invalid_plan",
                f"Step {step.id!r} has invalid dependencies.",
                {"unknown_dependencies": sorted(unknown_dependencies)},
            )
        for ref in step.input_refs.values():
            if not _REF_PATTERN.fullmatch(ref):
                raise InvalidPlan(
                    "invalid_plan",
                    f"Step {step.id!r} contains an unsupported input reference.",
                    {"reference": ref},
                )
            if ref.startswith("result."):
                source_step_id = ref.removeprefix("result.").split(".", 1)[0]
                if source_step_id not in step.depends_on:
                    raise InvalidPlan(
                        "invalid_plan",
                        "Result input references must point to a declared dependency.",
                        {"step_id": step.id, "reference": ref},
                    )

    _validate_dag(parsed.steps)
    _validate_dependencies(parsed.steps, normalized_agents)
    _validate_refs(parsed.steps, context)
    _validate_required_inputs(parsed.steps, normalized_agents, context)

    return ExecutionPlan(
        steps=[
            PlanStep(
                id=step.id,
                agent=normalized_agents[step.id],  # validated allow-list value
                depends_on=step.depends_on,
                input_refs=step.input_refs,
            )
            for step in parsed.steps
        ],
        source=source,  # type: ignore[arg-type]
    )


def _validate_dag(steps: list[ProposedStep]) -> None:
    step_ids = {step.id for step in steps}
    visited: set[str] = set()
    visiting: set[str] = set()
    by_id = {step.id: step for step in steps}

    def visit(step_id: str) -> None:
        if step_id in visiting:
            raise InvalidPlan("invalid_plan", "Plan dependencies must form a DAG.")
        if step_id in visited:
            return
        visiting.add(step_id)
        for dependency in by_id[step_id].depends_on:
            if dependency not in step_ids:
                raise InvalidPlan(
                    "invalid_plan",
                    f"Unknown dependency {dependency!r}.",
                    {"step_id": step_id},
                )
            visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step in steps:
        visit(step.id)


def _validate_dependencies(
    steps: list[ProposedStep],
    agents: dict[str, str],
) -> None:
    by_agent = {agent: step for step, agent in agents.items()}
    for step in steps:
        agent = agents[step.id]
        dependency_agents = {agents[dependency] for dependency in step.depends_on}
        required = {
            "budget_planning": {"expense_analysis"},
            "financial_report": {"expense_analysis", "budget_planning"},
        }.get(agent, set())
        if not required.issubset(dependency_agents):
            raise InvalidPlan(
                "invalid_plan",
                f"{agent} step must depend on {', '.join(sorted(required))}.",
                {"step_id": step.id, "required_dependencies": sorted(required)},
            )
        # Research can be attached to report as an optional dependency, but is
        # never mandatory for report generation.
        if agent == "financial_research" and step.depends_on:
            raise InvalidPlan(
                "invalid_plan",
                "Research steps are independent and cannot depend on other agents.",
                {"step_id": step.id},
            )
    del by_agent


def _validate_refs(steps: list[ProposedStep], context: dict[str, Any]) -> None:
    for step in steps:
        for key, reference in step.input_refs.items():
            if reference.startswith("context."):
                path = reference.removeprefix("context.")
                if _resolve_path(context, path) is _MISSING:
                    raise MissingWorkflowInput([path])
            if reference.startswith("result."):
                source_id = reference.removeprefix("result.").split(".", 1)[0]
                if source_id not in step.depends_on:
                    raise InvalidPlan(
                        "invalid_plan",
                        f"Input {key!r} references a non-dependency.",
                    )


def _validate_required_inputs(
    steps: list[ProposedStep],
    agents: dict[str, str],
    context: dict[str, Any],
) -> None:
    for step in steps:
        agent = agents[step.id]
        refs = step.input_refs
        if agent == "expense_analysis":
            profile_ref = refs.get("profile")
            if profile_ref != "context.profile":
                raise MissingWorkflowInput(["profile (profile_id, currency, and transactions)"])
            profile = _resolve_path(context, "profile")
            if profile is not _MISSING:
                transactions = (
                    profile.get("transactions")
                    if isinstance(profile, dict)
                    else getattr(profile, "transactions", None)
                )
                if not transactions:
                    raise MissingWorkflowInput(["profile.transactions"])
        elif agent == "financial_research":
            question_ref = refs.get("question")
            question_value = (
                _resolve_path(context, question_ref.removeprefix("context."))
                if question_ref is not None and question_ref.startswith("context.")
                else _MISSING
            )
            has_context_question = (
                question_value is not _MISSING
                and question_value is not None
                and question_value != ""
            )
            if question_ref != "task" and not has_context_question and not context.get("research_question"):
                raise MissingWorkflowInput(["research question"])
        elif agent == "budget_planning":
            expense_step = next(
                (
                    candidate
                    for candidate in steps
                    if agents[candidate.id] == "expense_analysis"
                    and candidate.id in step.depends_on
                ),
                None,
            )
            if expense_step is None or refs.get("expense_analysis") != f"result.{expense_step.id}":
                raise InvalidPlan(
                    "invalid_plan",
                    "Budget planning requires an expense-analysis result input.",
                    {"step_id": step.id},
                )
        elif agent == "financial_report":
            for input_name, upstream_agent in (
                ("expense_analysis", "expense_analysis"),
                ("budget", "budget_planning"),
            ):
                upstream_step = next(
                    (
                        candidate
                        for candidate in steps
                        if agents[candidate.id] == upstream_agent
                        and candidate.id in step.depends_on
                    ),
                    None,
                )
                expected_ref = (
                    f"result.{upstream_step.id}" if upstream_step is not None else None
                )
                if expected_ref is None or refs.get(input_name) != expected_ref:
                    raise InvalidPlan(
                        "invalid_plan",
                        f"Financial report requires the {upstream_agent} result as {input_name}.",
                        {"step_id": step.id, "input": input_name},
                    )


def _optional_context_refs(context: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    return {
        name: f"context.{name}"
        for name in names
        if name in context
    }


def _has_profile_input(context: dict[str, Any]) -> bool:
    profile = _resolve_path(context, "profile")
    if profile is not _MISSING:
        return True
    transactions = context.get("transactions")
    return bool(transactions and context.get("profile_id"))


_MISSING = object()


def _resolve_path(root: Any, path: str) -> Any:
    value = root
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                return _MISSING
            value = value[part]
        else:
            value = getattr(value, part, _MISSING)
            if value is _MISSING:
                return _MISSING
    return value


def plan_prompt(task: str, context: dict[str, Any]) -> str:
    """Describe task/context shape without sending financial values to planning."""
    return json.dumps(
        {
            "task": task,
            "context_keys": sorted(context),
            "has_profile": _has_profile_input(context),
            "has_transactions": bool(context.get("transactions")),
            "available_agents": sorted(_SUPPORTED_AGENTS),
            "rules": [
                "budget_planning depends on expense_analysis",
                "financial_report depends on expense_analysis and budget_planning",
                "financial_research is independent and optional for a report",
                "do not include agents not requested by task intent",
            ],
        },
        sort_keys=True,
    )
