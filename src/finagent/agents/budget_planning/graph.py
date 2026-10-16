"""LangGraph workflow for validated, deterministic budget planning."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from finagent.agents.budget_planning.allocation import (
    DEFAULT_DISCRETIONARY_FLOOR,
    DEFAULT_ESSENTIAL_CATEGORIES,
    BaselineAllocation,
    baseline_allocation,
    invariant_violations,
)
from finagent.agents.budget_planning.prompts import (
    SYSTEM_PROMPT,
    BudgetProposal,
    proposal_prompt,
)
from finagent.schemas.budget import (
    BudgetPlan,
    BudgetRequest,
    CategoryBudget,
    Feasibility,
    RevisionInfo,
)
from finagent.schemas.common import (
    AgentError,
    AgentStatus,
    ExpenseCategory,
    Limitation,
    Money,
    compute_version,
)
from finagent.schemas.expense import ExpenseAnalysisResult


class _BudgetState(TypedDict, total=False):
    request: Any
    parsed_request: BudgetRequest
    allocation: BaselineAllocation
    proposal: BudgetProposal
    chosen_limits: dict[ExpenseCategory, Decimal]
    rationales: dict[ExpenseCategory, str]
    assumptions: list[str]
    trade_offs: list[str]
    limitations: list[Limitation]
    llm_error: bool
    revision: int
    revision_info: RevisionInfo
    result: BudgetPlan


def _fallback_feasibility() -> Feasibility:
    zero = Money(amount=Decimal("0"))
    return Feasibility(
        is_feasible=False,
        requested_monthly_savings=zero,
        max_achievable_monthly_savings=zero,
        shortfall=zero,
        suggestions=[],
    )


def _failed_plan(
    *,
    code: str,
    message: str,
    currency: str = "INR",
    income: Decimal = Decimal("0"),
    analysis_version: str | None = None,
    revision: int = 1,
    revision_info: RevisionInfo | None = None,
) -> BudgetPlan:
    return BudgetPlan(
        status=AgentStatus.failed,
        errors=[AgentError(code=code, message=message)],
        revision=revision,
        source_analysis_version=analysis_version,
        currency=currency,
        monthly_income=Money(amount=income),
        category_limits=[],
        planned_monthly_savings=Money(amount=Decimal("0")),
        feasibility=_fallback_feasibility(),
        revision_info=revision_info,
    )


def _versioned_id(
    request: BudgetRequest,
    target: Decimal,
    revision: int,
    floor_rate: Decimal = DEFAULT_DISCRETIONARY_FLOOR,
) -> str:
    summary = request.expense_analysis.summary
    if summary is None or not request.expense_analysis.analysis_version:
        raise ValueError("a versioned expense analysis with summary is required")
    essential_categories = sorted(
        category.value
        for category in (
            request.essential_categories
            if request.essential_categories is not None
            else DEFAULT_ESSENTIAL_CATEGORIES
        )
    )
    return compute_version(
        "bp",
        {
            "source_analysis_version": request.expense_analysis.analysis_version,
            "target": target,
            "preferences": {
                "essential_categories": essential_categories,
                "discretionary_floor_rate": floor_rate,
                "currency": request.currency or summary.currency,
            },
            "revision": revision,
        },
    )


def build_budget_graph(llm: Any | None = None) -> Any:
    """Build the Budget Planning StateGraph.

    ``llm=None`` lazily uses the configured FinAgent provider. Pass ``llm=False``
    to run deterministic baseline-only mode without initializing a provider.
    """

    def validate_request(state: _BudgetState) -> dict[str, Any]:
        revision = state.get("revision", 1)
        try:
            request = BudgetRequest.model_validate(state.get("request"))
        except ValidationError as exc:
            return {
                "result": _failed_plan(
                    code="invalid_request",
                    message="The budget request did not match the shared schema: "
                    + "; ".join(error["msg"] for error in exc.errors()),
                    revision=revision,
                    revision_info=state.get("revision_info"),
                )
            }

        analysis = request.expense_analysis
        summary = analysis.summary
        if analysis.status == AgentStatus.failed:
            return {
                "result": _failed_plan(
                    code="analysis_failed",
                    message="Budget planning requires a successful or partial expense analysis.",
                    currency=request.currency or (summary.currency if summary else "INR"),
                    income=summary.monthly_income.amount if summary else Decimal("0"),
                    analysis_version=analysis.analysis_version,
                    revision=revision,
                    revision_info=state.get("revision_info"),
                )
            }
        if summary is None:
            return {
                "result": _failed_plan(
                    code="missing_analysis_summary",
                    message="Budget planning requires an expense-analysis summary.",
                    currency=request.currency or "INR",
                    analysis_version=analysis.analysis_version,
                    revision=revision,
                    revision_info=state.get("revision_info"),
                )
            }
        if not analysis.analysis_version:
            return {
                "result": _failed_plan(
                    code="missing_analysis_version",
                    message="Budget planning requires a non-empty analysis_version.",
                    currency=request.currency or summary.currency,
                    income=summary.monthly_income.amount,
                    revision=revision,
                    revision_info=state.get("revision_info"),
                )
            }
        if request.currency is not None and request.currency != summary.currency:
            return {
                "result": _failed_plan(
                    code="currency_mismatch",
                    message="Requested currency does not match the expense-analysis currency.",
                    currency=request.currency,
                    income=summary.monthly_income.amount,
                    analysis_version=analysis.analysis_version,
                    revision=revision,
                    revision_info=state.get("revision_info"),
                )
            }
        return {"parsed_request": request}

    def route_after_validation(state: _BudgetState) -> str:
        return "finish" if state.get("result") is not None else "baseline"

    def baseline(state: _BudgetState) -> dict[str, Any]:
        try:
            allocation = baseline_allocation(state["parsed_request"])
        except (ValueError, ArithmeticError) as exc:
            request = state["parsed_request"]
            summary = request.expense_analysis.summary
            return {
                "result": _failed_plan(
                    code="allocation_failed",
                    message=f"Deterministic baseline allocation failed: {exc}",
                    currency=summary.currency if summary else "INR",
                    income=summary.monthly_income.amount if summary else Decimal("0"),
                    analysis_version=request.expense_analysis.analysis_version,
                    revision=state.get("revision", 1),
                    revision_info=state.get("revision_info"),
                )
            }
        return {
            "allocation": allocation,
            "chosen_limits": allocation.limits,
            "rationales": {
                category: (
                    "Essential spending is preserved at its current average."
                    if category in allocation.essential_categories
                    else "Deterministic proportional allocation within the configured floor."
                )
                for category in allocation.limits
            },
            "assumptions": allocation.assumptions,
            "trade_offs": [],
            "limitations": [],
        }

    def route_after_baseline(state: _BudgetState) -> str:
        return "finish" if state.get("result") is not None else "propose"

    def propose(state: _BudgetState) -> dict[str, Any]:
        if llm is False:
            return {}
        allocation = state["allocation"]
        request = state["parsed_request"]
        summary = request.expense_analysis.summary
        assert summary is not None
        discretionary = [
            category
            for category in allocation.current_spend
            if category not in allocation.essential_categories
        ]
        try:
            model = llm
            if model is None:
                from finagent.llm import get_llm

                model = get_llm()
            structured_model = model.with_structured_output(BudgetProposal)
            response = structured_model.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(
                        content=proposal_prompt(
                            currency=summary.currency,
                            income=str(allocation.income),
                            target=str(allocation.target),
                            categories=[
                                {
                                    "category": category.value,
                                    "current": str(allocation.current_spend[category]),
                                    "floor": str(
                                        (allocation.current_spend[category] * allocation.floor_rate).quantize(
                                            Decimal("0.01"), rounding=ROUND_HALF_UP
                                        )
                                    ),
                                    "baseline_limit": str(allocation.limits[category]),
                                }
                                for category in discretionary
                            ],
                        )
                    ),
                ]
            )
        except Exception:
            return {
                "llm_error": True,
                "limitations": state.get("limitations", [])
                + [
                    Limitation(
                        code="llm_proposal_unavailable",
                        message="The LLM proposal was unavailable; the deterministic baseline is used.",
                    )
                ],
            }
        try:
            return {"proposal": BudgetProposal.model_validate(response)}
        except (ValidationError, TypeError, ValueError):
            return {
                "llm_error": True,
                "limitations": state.get("limitations", [])
                + [
                    Limitation(
                        code="llm_proposal_rejected",
                        message="The LLM proposal did not match the required non-negative structured format; "
                        "the deterministic baseline is used.",
                    )
                ],
            }

    def verify(state: _BudgetState) -> dict[str, Any]:
        proposal = state.get("proposal")
        if proposal is None:
            return {}
        allocation = state["allocation"]
        request = state["parsed_request"]
        discretionary = {
            category
            for category in allocation.current_spend
            if category not in allocation.essential_categories
        }
        proposal_categories = [item.category for item in proposal.category_adjustments]
        problems: list[str] = []
        if len(proposal_categories) != len(set(proposal_categories)):
            problems.append("The proposal contains duplicate categories.")
        if set(proposal_categories) != discretionary:
            problems.append("The proposal must cover every discretionary category and no others.")

        limits = dict(allocation.limits)
        rationales = dict(state["rationales"])
        for item in proposal.category_adjustments:
            category = item.category
            if category not in discretionary:
                continue
            amount = item.monthly_limit.amount
            floor = (
                allocation.current_spend[category] * allocation.floor_rate
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if amount < floor or amount > allocation.current_spend[category]:
                problems.append(f"{category.value} is outside its permitted floor/current range.")
            limits[category] = amount
            rationales[category] = item.rationale

        savings = allocation.income - sum(limits.values(), Decimal("0"))
        problems.extend(invariant_violations(allocation, limits, savings))
        if savings < allocation.target:
            problems.append("The proposal does not meet the savings target.")
        if problems:
            return {
                "chosen_limits": allocation.limits,
                "rationales": state["rationales"],
                "limitations": state.get("limitations", [])
                + [
                    Limitation(
                        code="llm_proposal_rejected",
                        message="The LLM proposal was rejected; the deterministic baseline is used. "
                        + " ".join(dict.fromkeys(problems)),
                    )
                ],
            }
        return {
            "chosen_limits": limits,
            "rationales": rationales,
            "assumptions": state.get("assumptions", []) + proposal.assumptions,
            "trade_offs": proposal.trade_offs,
        }

    def assemble(state: _BudgetState) -> dict[str, Any]:
        request = state["parsed_request"]
        summary = request.expense_analysis.summary
        if summary is None:
            return {}
        allocation = state["allocation"]
        limits = state.get("chosen_limits", allocation.limits)
        savings = allocation.income - sum(limits.values(), Decimal("0"))

        # Essentials or their floor can exceed income; no valid plan can preserve
        # them and satisfy the shared BudgetPlan income invariant simultaneously.
        violations = invariant_violations(allocation, limits, savings)
        if violations:
            return {
                "result": _failed_plan(
                    code="unaffordable_obligations",
                    message="No valid budget can preserve essential obligations within income.",
                    currency=summary.currency,
                    income=allocation.income,
                    analysis_version=request.expense_analysis.analysis_version,
                    revision=state.get("revision", 1),
                    revision_info=state.get("revision_info"),
                )
            }
        categories = [
            CategoryBudget(
                category=category,
                monthly_limit=Money(amount=limits[category]),
                current_monthly_spend=Money(amount=allocation.current_spend[category]),
                is_essential=category in allocation.essential_categories,
                rationale=state.get("rationales", {}).get(category, ""),
            )
            for category in sorted(limits, key=lambda item: item.value)
        ]
        revision = state.get("revision", 1)
        plan = BudgetPlan(
            status=(
                AgentStatus.partial
                if state.get("llm_error") or state.get("limitations")
                else AgentStatus.success
            ),
            limitations=state.get("limitations", []),
            budget_id=_versioned_id(request, allocation.target, revision),
            revision=revision,
            source_analysis_version=request.expense_analysis.analysis_version,
            currency=summary.currency,
            monthly_income=Money(amount=allocation.income),
            essential_categories=sorted(
                allocation.essential_categories,
                key=lambda category: category.value,
            ),
            category_limits=categories,
            planned_monthly_savings=Money(amount=savings),
            feasibility=allocation.feasibility,
            assumptions=state.get("assumptions", []),
            trade_offs=state.get("trade_offs", []),
            revision_info=state.get("revision_info"),
        )
        return {"result": plan}

    graph = StateGraph(_BudgetState)
    graph.add_node("validate_request", validate_request)
    graph.add_node("baseline", baseline)
    graph.add_node("propose", propose)
    graph.add_node("verify", verify)
    graph.add_node("assemble", assemble)
    graph.add_edge(START, "validate_request")
    graph.add_conditional_edges(
        "validate_request",
        route_after_validation,
        {"finish": END, "baseline": "baseline"},
    )
    graph.add_conditional_edges(
        "baseline",
        route_after_baseline,
        {"finish": END, "propose": "propose"},
    )
    graph.add_edge("propose", "verify")
    graph.add_edge("verify", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def _run(
    request: BudgetRequest | dict[str, Any],
    llm: Any | None,
    *,
    revision: int = 1,
    revision_info: RevisionInfo | None = None,
) -> BudgetPlan:
    try:
        state = build_budget_graph(llm=llm).invoke(
            {
                "request": request,
                "revision": revision,
                "revision_info": revision_info,
            }
        )
        result = state.get("result")
        if isinstance(result, BudgetPlan):
            return result
        return _failed_plan(
            code="missing_result",
            message="Budget planning completed without a plan.",
            revision=revision,
            revision_info=revision_info,
        )
    except Exception:
        return _failed_plan(
            code="agent_execution_error",
            message="Budget planning could not be completed.",
            revision=revision,
            revision_info=revision_info,
        )


def run_budget_planning(
    request: BudgetRequest | dict[str, Any],
    llm: Any | None = None,
) -> BudgetPlan:
    """Run budget planning and return expected failures as structured plans."""
    return _run(request, llm)


def revise_budget(
    previous: BudgetPlan,
    new_analysis: ExpenseAnalysisResult,
    llm: Any | None = None,
    *,
    savings_goal: Any | None = None,
    essential_categories: Any | None = None,
) -> BudgetPlan:
    """Rebuild a versioned plan, retaining preferences unless explicitly changed."""
    if (
        savings_goal is None
        and essential_categories is None
        and new_analysis.status != AgentStatus.failed
        and new_analysis.summary is not None
        and new_analysis.analysis_version
        and new_analysis.analysis_version == previous.source_analysis_version
        and new_analysis.summary.currency == previous.currency
    ):
        return previous.model_copy(
            update={
                "limitations": previous.limitations
                + [
                    Limitation(
                        code="revision_not_needed",
                        message="The expense analysis version is unchanged; the previous budget plan was retained.",
                    )
                ]
            }
        )

    summary = new_analysis.summary
    previous_essentials = previous.essential_categories or [
        item.category for item in previous.category_limits if item.is_essential
    ]
    request = BudgetRequest(
        expense_analysis=new_analysis,
        savings_goal=savings_goal or {
            "monthly_target": previous.feasibility.requested_monthly_savings
        },
        essential_categories=essential_categories if essential_categories is not None else previous_essentials or None,
        currency=previous.currency,
    )
    revision = previous.revision + 1
    source_version = new_analysis.analysis_version or ""
    revision_info = RevisionInfo(
        parent_budget_id=previous.budget_id or "",
        previous_source_analysis_version=previous.source_analysis_version or "",
        changes=[],
    )
    result = _run(
        request,
        llm,
        revision=revision,
        revision_info=revision_info,
    )
    if result.status == AgentStatus.failed or summary is None:
        return result

    old_limits = {item.category: item.monthly_limit.amount for item in previous.category_limits}
    new_limits = {item.category: item.monthly_limit.amount for item in result.category_limits}
    changes = [
        f"{category.value}: {old_limits.get(category, Decimal('0.00')):.2f} -> "
        f"{new_limits.get(category, Decimal('0.00')):.2f} "
        f"(delta {new_limits.get(category, Decimal('0.00')) - old_limits.get(category, Decimal('0.00')):+.2f})"
        for category in sorted(set(old_limits) | set(new_limits), key=lambda item: item.value)
    ]
    return result.model_copy(
        update={
            "revision_info": revision_info.model_copy(update={"changes": changes}),
            "source_analysis_version": source_version,
        }
    )
