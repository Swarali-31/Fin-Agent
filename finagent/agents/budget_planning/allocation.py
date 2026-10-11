"""Deterministic budget allocation and feasibility calculations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from finagent.schemas.budget import BudgetRequest, Feasibility
from finagent.schemas.common import ExpenseCategory, Money

CENT = Decimal("0.01")
DEFAULT_DISCRETIONARY_FLOOR = Decimal("0.40")
DEFAULT_ESSENTIAL_CATEGORIES = frozenset(
    {
        ExpenseCategory.housing,
        ExpenseCategory.utilities,
        ExpenseCategory.groceries,
        ExpenseCategory.healthcare,
        ExpenseCategory.insurance,
        ExpenseCategory.debt_payment,
        ExpenseCategory.transport,
        ExpenseCategory.education,
    }
)


@dataclass(frozen=True, slots=True)
class BaselineAllocation:
    """Amounts and supporting facts for the deterministic baseline."""

    income: Decimal
    target: Decimal
    current_spend: dict[ExpenseCategory, Decimal]
    limits: dict[ExpenseCategory, Decimal]
    essential_categories: frozenset[ExpenseCategory]
    floor_rate: Decimal
    feasibility: Feasibility
    assumptions: list[str]


def _quantize(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _money(amount: Decimal) -> Money:
    return Money(amount=_quantize(amount))


def _floor_amount(amount: Decimal, floor_rate: Decimal) -> Decimal:
    return _quantize(amount * floor_rate)


def _allocate_cents(total: Decimal, weights: dict[ExpenseCategory, Decimal]) -> dict[ExpenseCategory, Decimal]:
    """Split a non-negative amount proportionally, distributing residual cents deterministically."""
    cents = int((_quantize(total) / CENT).to_integral_value())
    total_weight = sum(weights.values(), Decimal("0"))
    if cents <= 0 or total_weight <= 0:
        return {category: Decimal("0.00") for category in weights}

    exact_shares = {
        category: Decimal(cents) * weight / total_weight
        for category, weight in weights.items()
    }
    whole_cents = {
        category: int(share.to_integral_value(rounding=ROUND_DOWN))
        for category, share in exact_shares.items()
    }
    remainder = cents - sum(whole_cents.values())
    remainder_order = sorted(
        weights,
        key=lambda category: (
            -(exact_shares[category] - whole_cents[category]),
            category.value,
        ),
    )
    for category in remainder_order[:remainder]:
        whole_cents[category] += 1
    return {category: Decimal(value) * CENT for category, value in whole_cents.items()}


def check_feasibility(
    income: Decimal,
    current_spend: dict[ExpenseCategory, Decimal],
    target: Decimal,
    essential_categories: frozenset[ExpenseCategory],
    floor_rate: Decimal = DEFAULT_DISCRETIONARY_FLOOR,
) -> Feasibility:
    """Calculate the achievable savings ceiling and actionable shortfall suggestions."""
    essentials = sum(
        (amount for category, amount in current_spend.items() if category in essential_categories),
        Decimal("0"),
    )
    floors = {
        category: _floor_amount(amount, floor_rate)
        for category, amount in current_spend.items()
        if category not in essential_categories
    }
    max_savings = max(
        Decimal("0.00"),
        _quantize(income - essentials - sum(floors.values(), Decimal("0"))),
    )
    shortfall = max(Decimal("0.00"), _quantize(target - max_savings))
    suggestions: list[str] = []
    if shortfall > 0:
        suggestions.append(
            f"Lower the monthly savings target to no more than {max_savings:.2f}."
        )
        reducible = sorted(
            (
                (category, floor)
                for category, floor in floors.items()
                if floor > 0
            ),
            key=lambda item: (-item[1], item[0].value),
        )
        if reducible:
            names = ", ".join(
                f"{category.value} (up to {floor:.2f} below the configured floor)"
                for category, floor in reducible
            )
            suggestions.append(
                f"Consider reducing discretionary categories below their configured floors: {names}."
            )
        suggestions.append(f"Increase monthly income by at least {shortfall:.2f}.")
    return Feasibility(
        is_feasible=shortfall == 0,
        requested_monthly_savings=_money(target),
        max_achievable_monthly_savings=_money(max_savings),
        shortfall=_money(shortfall),
        suggestions=suggestions,
    )


def baseline_allocation(
    request: BudgetRequest,
    discretionary_floor_rate: Decimal = DEFAULT_DISCRETIONARY_FLOOR,
) -> BaselineAllocation:
    """Create an exact, proportional baseline without using a language model."""
    if not Decimal("0") <= discretionary_floor_rate <= Decimal("1"):
        raise ValueError("discretionary_floor_rate must be between 0 and 1")
    summary = request.expense_analysis.summary
    if summary is None:
        raise ValueError("expense_analysis.summary is required")

    income = summary.monthly_income.amount
    current = {
        category: amount.amount
        for category, amount in summary.category_totals.items()
    }
    essential_categories = frozenset(
        request.essential_categories
        if request.essential_categories is not None
        else DEFAULT_ESSENTIAL_CATEGORIES
    )
    protect_uncategorized = request.essential_categories is None and any(gap.issue == "missing_category" for gap in request.expense_analysis.data_gaps)
    if protect_uncategorized:
        essential_categories = essential_categories | {ExpenseCategory.other}
    if request.savings_goal is None:
        target = _quantize(income * Decimal("0.20"))
        assumptions = [
            "No savings goal was provided; a target of 20% of monthly income was assumed."
        ]
    elif request.savings_goal.monthly_target is not None:
        target = request.savings_goal.monthly_target.amount
        assumptions = []
    else:
        rate = request.savings_goal.target_rate
        if rate is None:
            raise ValueError("savings_goal must contain a monthly target or target rate")
        target = _quantize(income * rate)
        assumptions = []

    feasibility = check_feasibility(
        income,
        current,
        target,
        essential_categories,
        discretionary_floor_rate,
    )
    limits = {
        category: amount
        for category, amount in current.items()
        if category in essential_categories
    }
    discretionary = {
        category: amount
        for category, amount in current.items()
        if category not in essential_categories
    }
    floors = {
        category: _floor_amount(amount, discretionary_floor_rate)
        for category, amount in discretionary.items()
    }
    essential_total = sum(limits.values(), Decimal("0"))
    discretionary_total = sum(discretionary.values(), Decimal("0"))
    floor_total = sum(floors.values(), Decimal("0"))

    desired_discretionary = min(
        discretionary_total,
        max(Decimal("0.00"), _quantize(income - target - essential_total)),
    )
    if not feasibility.is_feasible:
        desired_discretionary = floor_total
    desired_discretionary = max(floor_total, desired_discretionary)

    extra_budget = _quantize(desired_discretionary - floor_total)
    capacities = {
        category: max(Decimal("0.00"), amount - floors[category])
        for category, amount in discretionary.items()
    }
    extras = _allocate_cents(extra_budget, capacities)
    limits.update(
        {
            category: _quantize(floors[category] + extras[category])
            for category in discretionary
        }
    )
    if protect_uncategorized:
        assumptions.append("Uncategorized spending is kept at its current level until you confirm which costs are flexible. Correct categories or choose essential expenses to refine this budget.")
    if summary.refund_total and summary.refund_total.amount > 0:
        assumptions.append("Money received includes refunds. Refunds are not regular earnings; confirm that future income can support this plan.")
    return BaselineAllocation(
        income=income,
        target=target,
        current_spend=current,
        limits=limits,
        essential_categories=essential_categories,
        floor_rate=discretionary_floor_rate,
        feasibility=feasibility,
        assumptions=assumptions,
    )


def invariant_violations(
    allocation: BaselineAllocation,
    limits: dict[ExpenseCategory, Decimal],
    savings: Decimal,
) -> list[str]:
    """Return all violations of the planner's monetary and coverage invariants."""
    issues: list[str] = []
    if any(amount < 0 for amount in limits.values()):
        issues.append("Category limits cannot be negative.")
    missing = set(allocation.current_spend) - set(limits)
    extra = set(limits) - set(allocation.current_spend)
    if missing:
        issues.append("A category from the analysis is missing.")
    if extra:
        issues.append("A category not present in the analysis was added.")
    if any(
        limits.get(category, Decimal("0")) < allocation.current_spend[category]
        for category in allocation.essential_categories & set(allocation.current_spend)
    ):
        issues.append("An essential category was cut below its current spend.")
    total = sum(limits.values(), Decimal("0")) + savings
    if savings < 0 or total > allocation.income:
        issues.append("Category limits and savings exceed monthly income.")
    return issues
