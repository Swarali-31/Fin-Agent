from __future__ import annotations

from datetime import date
from decimal import Decimal

from finagent.agents.expense_analysis.calculations import (
    compute_expense_metrics,
    detect_recurring,
    find_data_gaps,
)
from finagent.schemas.common import ExpenseCategory, Money, TransactionType
from finagent.schemas.financial import FinancialProfile, Transaction
from finagent.sample_data import sample_profile


def test_summary_uses_exact_rounded_category_averages() -> None:
    profile = FinancialProfile(
        profile_id="rounding",
        currency="INR",
        transactions=[
            Transaction(
                id="income-1",
                date=date(2026, 1, 1),
                description="Salary",
                amount=Money(amount="100.00"),
                type=TransactionType.income,
            ),
            Transaction(
                id="food-1",
                date=date(2026, 1, 2),
                description="Food",
                amount=Money(amount="10.00"),
                type=TransactionType.expense,
                category=ExpenseCategory.dining,
            ),
            Transaction(
                id="travel-1",
                date=date(2026, 1, 3),
                description="Travel",
                amount=Money(amount="20.00"),
                type=TransactionType.expense,
                category=ExpenseCategory.transport,
            ),
            Transaction(
                id="income-2",
                date=date(2026, 2, 1),
                description="Salary",
                amount=Money(amount="101.00"),
                type=TransactionType.income,
            ),
            Transaction(
                id="food-2",
                date=date(2026, 2, 2),
                description="Food",
                amount=Money(amount="10.00"),
                type=TransactionType.expense,
                category=ExpenseCategory.dining,
            ),
            Transaction(
                id="travel-2",
                date=date(2026, 2, 3),
                description="Travel",
                amount=Money(amount="20.00"),
                type=TransactionType.expense,
                category=ExpenseCategory.transport,
            ),
        ],
    )

    summary = compute_expense_metrics(profile).summary
    assert summary.monthly_income.amount == Decimal("100.50")
    assert summary.category_totals[ExpenseCategory.dining].amount == Decimal("10.00")
    assert summary.category_totals[ExpenseCategory.transport].amount == Decimal("20.00")
    assert summary.monthly_expenses.amount == Decimal("30.00")
    assert summary.available_surplus.amount == Decimal("70.50")
    assert sum((item.amount for item in summary.category_totals.values()), Decimal("0")) == (
        summary.monthly_expenses.amount
    )


def test_sample_detects_recurring_expenses_and_data_gaps() -> None:
    profile = sample_profile()
    recurring = detect_recurring(profile)
    assert any(item.description == "Rent" and item.occurrences == 3 for item in recurring)

    gaps = find_data_gaps(profile)
    issues = {gap.issue for gap in gaps}
    assert "missing_category" in issues
    assert "ambiguous_recurring_status" in issues
    assert "vague_description" in issues
    assert "insufficient_history" not in issues
    assert "no_income" not in issues
    assert not any(
        gap.transaction_id == "exp-electronics-2026-07" and gap.issue == "vague_description"
        for gap in gaps
    )


def test_uncategorized_expenses_are_included_in_summary_as_other() -> None:
    summary = compute_expense_metrics(sample_profile()).summary
    assert summary.category_totals[ExpenseCategory.other].amount == Decimal("666.67")
    assert sum((item.amount for item in summary.category_totals.values()), Decimal("0")) == (
        summary.monthly_expenses.amount
    )


def test_analysis_version_tracks_profile_content() -> None:
    profile = sample_profile()
    original = compute_expense_metrics(profile).analysis_version
    assert compute_expense_metrics(profile).analysis_version == original

    changed_profile = profile.model_copy(deep=True)
    changed_profile.transactions[0].description = "Updated salary description"
    assert compute_expense_metrics(changed_profile).analysis_version != original


def test_single_month_without_income_reports_history_and_income_gaps() -> None:
    profile = FinancialProfile(
        profile_id="incomplete",
        transactions=[
            Transaction(
                id="expense-1",
                date=date(2026, 1, 1),
                description="Unclear charge",
                amount=Money(amount="12.00"),
                type=TransactionType.expense,
                is_recurring=None,
            )
        ],
    )

    gaps = find_data_gaps(profile)
    issues = {gap.issue for gap in gaps}
    assert "insufficient_history" in issues
    assert "no_income" in issues


def test_sample_flags_large_purchase_and_duplicate_transactions() -> None:
    metrics = compute_expense_metrics(sample_profile())
    outliers = {
        item.transaction_id for item in metrics.unusual_transactions if item.kind == "outlier"
    }
    duplicates = {
        item.transaction_id
        for item in metrics.unusual_transactions
        if item.kind == "possible_duplicate"
    }
    assert "exp-electronics-2026-07" in outliers
    assert {"exp-dine-dup-a", "exp-dine-dup-b"}.issubset(duplicates)


def test_recurring_detection_requires_cross_month_amount_stability() -> None:
    recurring = detect_recurring(sample_profile())
    descriptions = {item.description for item in recurring}
    assert "Rent" in descriptions
    assert "Groceries" not in descriptions