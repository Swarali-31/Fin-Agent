from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from finagent.agents.budget_planning.graph import revise_budget, run_budget_planning
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.sample_data import (
    sample_profile,
    sample_savings_goal_feasible,
    sample_savings_goal_infeasible,
)
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    TransactionType,
)
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import Transaction


def _analysis(*, version: str | None = None) -> ExpenseAnalysisResult:
    metrics = compute_expense_metrics(sample_profile())
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=version if version is not None else metrics.analysis_version,
        summary=metrics.summary,
    )


def _budget_request(goal: Any = None) -> BudgetRequest:
    return BudgetRequest(
        expense_analysis=_analysis(),
        savings_goal=goal,
    )


class FakeChatModel:
    def __init__(self, response: Any) -> None:
        self.response = response

    def with_structured_output(self, schema: type) -> FakeChatModel:
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _unmodified_proposal() -> dict[str, object]:
    analysis = _analysis()
    categories = analysis.summary.category_totals if analysis.summary else {}
    essentials = {
        ExpenseCategory.housing,
        ExpenseCategory.utilities,
        ExpenseCategory.groceries,
        ExpenseCategory.healthcare,
        ExpenseCategory.insurance,
        ExpenseCategory.debt_payment,
        ExpenseCategory.transport,
        ExpenseCategory.education,
    }
    return {
        "category_adjustments": [
            {
                "category": category.value,
                "monthly_limit": {"amount": str(amount.amount)},
                "rationale": "Maintain this proposed baseline.",
            }
            for category, amount in categories.items()
            if category not in essentials
        ],
        "assumptions": [],
        "trade_offs": [],
    }


def test_feasible_goal_succeeds_and_limits_plus_savings_stay_within_income() -> None:
    plan = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)
    total = sum((item.monthly_limit.amount for item in plan.category_limits), Decimal("0"))

    assert plan.status == AgentStatus.success
    assert plan.feasibility.is_feasible
    assert total + plan.planned_monthly_savings.amount <= plan.monthly_income.amount
    assert {item.category for item in plan.category_limits} == set(
        _analysis().summary.category_totals if _analysis().summary else {}
    )


def test_infeasible_goal_returns_shortfall_and_suggestions() -> None:
    plan = run_budget_planning(_budget_request(sample_savings_goal_infeasible()), llm=False)

    assert plan.status == AgentStatus.success
    assert not plan.feasibility.is_feasible
    assert plan.feasibility.shortfall.amount == (
        plan.feasibility.requested_monthly_savings.amount
        - plan.feasibility.max_achievable_monthly_savings.amount
    )
    assert plan.feasibility.suggestions


def test_over_budget_llm_proposal_is_rejected_in_favor_of_baseline() -> None:
    response = _unmodified_proposal()
    adjustments = response["category_adjustments"]
    assert isinstance(adjustments, list)
    adjustments[0]["monthly_limit"] = {"amount": "999999.00"}

    plan = run_budget_planning(
        _budget_request(sample_savings_goal_feasible()),
        llm=FakeChatModel(response),
    )
    baseline = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)

    assert plan.status == AgentStatus.partial
    assert [
        item.monthly_limit.amount for item in plan.category_limits
    ] == [item.monthly_limit.amount for item in baseline.category_limits]
    assert any(item.code == "llm_proposal_rejected" for item in plan.limitations)


def test_negative_llm_limit_is_rejected_in_favor_of_baseline() -> None:
    response = _unmodified_proposal()
    adjustments = response["category_adjustments"]
    assert isinstance(adjustments, list)
    adjustments[0]["monthly_limit"] = {"amount": "-1.00"}

    plan = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=FakeChatModel(response))
    baseline = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)

    assert plan.status == AgentStatus.partial
    assert any(item.code == "llm_proposal_rejected" for item in plan.limitations)
    assert plan.category_limits == baseline.category_limits


def test_valid_structured_llm_proposal_is_accepted() -> None:
    baseline = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)
    response = {
        "category_adjustments": [
            {
                "category": item.category.value,
                "monthly_limit": {"amount": str(item.monthly_limit.amount)},
                "rationale": "Use the verified baseline limit.",
            }
            for item in baseline.category_limits
            if not item.is_essential
        ],
        "assumptions": ["The supplied average is representative."],
        "trade_offs": ["Discretionary purchases are reduced."],
    }

    plan = run_budget_planning(
        _budget_request(sample_savings_goal_feasible()),
        llm=FakeChatModel(response),
    )

    assert plan.status == AgentStatus.success
    assert plan.assumptions[-1] == "The supplied average is representative."
    assert plan.trade_offs == ["Discretionary purchases are reduced."]
    assert all(
        item.rationale == "Use the verified baseline limit."
        for item in plan.category_limits
        if not item.is_essential
    )


def test_failed_and_versionless_analyses_are_rejected() -> None:
    failed = _analysis().model_copy(update={"status": AgentStatus.failed})
    failed_plan = run_budget_planning({"expense_analysis": failed.model_dump(mode="python")}, llm=False)
    versionless = _analysis().model_copy(update={"analysis_version": None})
    versionless_plan = run_budget_planning(
        {"expense_analysis": versionless.model_dump(mode="python")},
        llm=False,
    )

    assert failed_plan.status == AgentStatus.failed
    assert failed_plan.errors[0].code == "analysis_failed"
    assert versionless_plan.status == AgentStatus.failed
    assert versionless_plan.errors[0].code == "missing_analysis_version"


def test_request_currency_mismatch_is_rejected() -> None:
    plan = run_budget_planning(
        {
            "expense_analysis": _analysis().model_dump(mode="python"),
            "currency": "USD",
        },
        llm=False,
    )

    assert plan.status == AgentStatus.failed
    assert plan.errors[0].code == "currency_mismatch"


def test_revision_increments_updates_source_and_records_category_deltas() -> None:
    previous = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)
    changed_profile = sample_profile().model_copy(deep=True)
    changed_profile.transactions.append(
        Transaction(
            id="exp-dining-after-change",
            date=date(2026, 9, 25),
            description="Restaurants",
            amount=Money(amount="12000.00"),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
        )
    )
    metrics = compute_expense_metrics(changed_profile)
    new_analysis = ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
    )

    revised = revise_budget(previous, new_analysis, llm=False)

    assert revised.revision == previous.revision + 1
    assert revised.source_analysis_version == new_analysis.analysis_version
    assert revised.revision_info is not None
    assert revised.revision_info.parent_budget_id == previous.budget_id
    assert revised.revision_info.changes
    assert any("dining:" in change for change in revised.revision_info.changes)


def test_same_version_revision_retains_plan_and_adds_info_limitation() -> None:
    previous = run_budget_planning(_budget_request(sample_savings_goal_feasible()), llm=False)
    repeated = revise_budget(previous, _analysis(), llm=False)

    assert repeated.budget_id == previous.budget_id
    assert repeated.revision == previous.revision
    assert repeated.category_limits == previous.category_limits
    assert repeated.source_analysis_version == previous.source_analysis_version
    assert any(item.code == "revision_not_needed" for item in repeated.limitations)
