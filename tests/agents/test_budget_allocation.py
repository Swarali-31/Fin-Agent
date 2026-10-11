from __future__ import annotations

from decimal import Decimal

from finagent.agents.budget_planning.allocation import (
    DEFAULT_ESSENTIAL_CATEGORIES,
    baseline_allocation,
)
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import AgentStatus, ExpenseCategory, Money
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import SavingsGoal
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.sample_data import sample_profile, sample_savings_goal_feasible, sample_savings_goal_infeasible


def _analysis() -> ExpenseAnalysisResult:
    metrics = compute_expense_metrics(sample_profile())
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
    )


def test_feasible_sample_goal_and_essentials_are_not_cut() -> None:
    request = BudgetRequest(
        expense_analysis=_analysis(),
        savings_goal=sample_savings_goal_feasible(),
    )
    allocation = baseline_allocation(request)

    assert allocation.feasibility.is_feasible
    assert allocation.feasibility.shortfall.amount == Decimal("0.00")
    assert allocation.limits[ExpenseCategory.housing] == allocation.current_spend[ExpenseCategory.housing]
    assert allocation.essential_categories == DEFAULT_ESSENTIAL_CATEGORIES
    assert all(
        allocation.limits[category] >= allocation.current_spend[category]
        for category in allocation.essential_categories & set(allocation.current_spend)
    )


def test_infeasible_sample_goal_reports_correct_shortfall_and_suggestions() -> None:
    allocation = baseline_allocation(
        BudgetRequest(
            expense_analysis=_analysis(),
            savings_goal=sample_savings_goal_infeasible(),
        )
    )

    assert not allocation.feasibility.is_feasible
    assert allocation.feasibility.shortfall.amount == (
        allocation.feasibility.requested_monthly_savings.amount
        - allocation.feasibility.max_achievable_monthly_savings.amount
    )
    assert allocation.feasibility.suggestions
    assert any("income" in suggestion for suggestion in allocation.feasibility.suggestions)


def test_proportional_allocation_is_decimal_exact_and_obeys_floor() -> None:
    request = BudgetRequest(
        expense_analysis=_analysis(),
        savings_goal=SavingsGoal(monthly_target=Money(amount="15000.00")),
    )
    allocation = baseline_allocation(request)
    actual_savings = allocation.income - sum(allocation.limits.values(), Decimal("0"))

    assert sum(allocation.limits.values(), Decimal("0")) + actual_savings == allocation.income
    assert actual_savings == Decimal("15000.00")
    for category, current in allocation.current_spend.items():
        if category not in allocation.essential_categories:
            assert allocation.limits[category] >= (current * Decimal("0.40")).quantize(
                Decimal("0.01")
            )
        else:
            assert allocation.limits[category] == current


def test_missing_goal_defaults_to_twenty_percent_of_income() -> None:
    allocation = baseline_allocation(BudgetRequest(expense_analysis=_analysis()))

    assert allocation.target == Decimal("17000.00")
    assert any("20% of monthly income" in item for item in allocation.assumptions)


def test_floor_rate_is_configurable() -> None:
    allocation = baseline_allocation(
        BudgetRequest(
            expense_analysis=_analysis(),
            savings_goal=sample_savings_goal_infeasible(),
        ),
        discretionary_floor_rate=Decimal("0.25"),
    )

    assert allocation.floor_rate == Decimal("0.25")
    for category, current in allocation.current_spend.items():
        if category not in allocation.essential_categories:
            assert allocation.limits[category] >= (current * Decimal("0.25")).quantize(
                Decimal("0.01")
            )


def test_unknown_expense_categories_are_not_silently_treated_as_flexible():
    from finagent.schemas.expense import DataGap
    analysis=_analysis()
    analysis.summary.category_totals[ExpenseCategory.other]=Money(amount='1000')
    analysis.data_gaps.append(DataGap(issue='missing_category',question='What is this cost?'))
    allocation=baseline_allocation(BudgetRequest(expense_analysis=analysis,savings_goal={'monthly_target':{'amount':'30000'}}))
    assert ExpenseCategory.other in allocation.essential_categories
    assert allocation.limits[ExpenseCategory.other]==Decimal('1000.00')
    assert any('Uncategorized spending' in text for text in allocation.assumptions)
