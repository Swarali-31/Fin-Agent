"""Deterministic expense metrics for a financial profile."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from finagent.schemas.common import (
    ExpenseCategory,
    Money,
    SignedMoney,
    TransactionType,
    compute_version,
)
from finagent.schemas.expense import DataGap, RecurringExpense, UnusualTransaction
from finagent.schemas.financial import FinancialProfile, FinancialSummary, Transaction

_CENT = Decimal("0.01")
_FIVE_PERCENT = Decimal("0.05")
_MODIFIED_Z_THRESHOLD = Decimal("3.5")
_MIN_OUTLIER_SAMPLE = 5
_VAGUE_TERMS = {
    "misc",
    "miscellaneous",
    "other",
    "uncategorized",
    "unclear",
    "unknown",
    "upi",
}
_GENERIC_MERCHANTS = {"atm", "mixed", "other", "upi", "various", "unknown"}


@dataclass(frozen=True, slots=True)
class ExpenseMetrics:
    """Computed output fields that do not require an LLM."""

    analysis_version: str
    summary: FinancialSummary
    recurring_expenses: list[RecurringExpense]
    unusual_transactions: list[UnusualTransaction]
    data_gaps: list[DataGap]


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _average(total: Decimal, count: int) -> Decimal:
    return _quantize(total / Decimal(count))


def _normalized(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _month(transaction: Transaction) -> str:
    return transaction.date.strftime("%Y-%m")


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _recurrence_key(transaction: Transaction) -> tuple[str, str, ExpenseCategory]:
    merchant = _normalized(transaction.merchant)
    if merchant and merchant not in _GENERIC_MERCHANTS:
        identity = ("merchant", merchant)
    else:
        identity = ("description", _normalized(transaction.description))
    category = transaction.category or ExpenseCategory.other
    return identity[0], identity[1], category


def detect_recurring(profile: FinancialProfile) -> list[RecurringExpense]:
    """Find explicit recurring expenses and stable cross-month expense patterns."""
    groups: dict[tuple[str, str, ExpenseCategory], list[Transaction]] = defaultdict(list)
    for transaction in profile.transactions:
        if transaction.type == TransactionType.expense:
            groups[_recurrence_key(transaction)].append(transaction)

    recurring_groups: list[list[Transaction]] = []
    for transactions in groups.values():
        months = {_month(transaction) for transaction in transactions}
        amounts = [transaction.amount.amount for transaction in transactions]
        is_stable_cross_month = (
            len(months) >= 2
            and max(amounts) - min(amounts) <= _median(amounts) * _FIVE_PERCENT
        )
        explicit = [transaction for transaction in transactions if transaction.is_recurring is True]
        if is_stable_cross_month:
            recurring_groups.append(transactions)
        elif explicit:
            recurring_groups.append(explicit)

    results: list[RecurringExpense] = []
    for transactions in recurring_groups:
        first = transactions[0]
        results.append(
            RecurringExpense(
                description=first.description,
                category=first.category or ExpenseCategory.other,
                monthly_amount=Money(
                    amount=_average(
                        sum((transaction.amount.amount for transaction in transactions), Decimal("0")),
                        len(transactions),
                    )
                ),
                occurrences=len(transactions),
            )
        )
    return sorted(results, key=lambda item: (item.category.value, _normalized(item.description)))


def _detect_unusual(profile: FinancialProfile) -> list[UnusualTransaction]:
    expense_transactions = [
        transaction
        for transaction in profile.transactions
        if transaction.type == TransactionType.expense
    ]
    grouped = _group_expenses(expense_transactions)
    recurring_keys = {
        _recurrence_key(transaction)
        for transaction in expense_transactions
        if transaction.is_recurring is True
    }
    recurring_keys.update(
        key
        for key, transactions in grouped.items()
        if len({_month(transaction) for transaction in transactions}) >= 2
        and max(transaction.amount.amount for transaction in transactions)
        - min(transaction.amount.amount for transaction in transactions)
        <= _median([transaction.amount.amount for transaction in transactions]) * _FIVE_PERCENT
    )
    non_recurring = [
        transaction
        for transaction in expense_transactions
        if _recurrence_key(transaction) not in recurring_keys
    ]

    outlier_ids: set[str] = set()
    if len(non_recurring) >= _MIN_OUTLIER_SAMPLE:
        amounts = [transaction.amount.amount for transaction in non_recurring]
        center = _median(amounts)
        mad = _median([abs(amount - center) for amount in amounts])
        if mad:
            for transaction in non_recurring:
                score = Decimal("0.6745") * abs(transaction.amount.amount - center) / mad
                if score > _MODIFIED_Z_THRESHOLD:
                    outlier_ids.add(transaction.id)

    duplicate_groups: dict[tuple[object, str, Decimal], list[Transaction]] = defaultdict(list)
    for transaction in expense_transactions:
        duplicate_groups[
            (transaction.date, _normalized(transaction.merchant), transaction.amount.amount)
        ].append(transaction)
    duplicate_ids = {
        transaction.id
        for transactions in duplicate_groups.values()
        if len(transactions) > 1
        for transaction in transactions
    }

    by_id = {transaction.id: transaction for transaction in expense_transactions}
    results: list[UnusualTransaction] = []
    for transaction_id in sorted(outlier_ids | duplicate_ids):
        transaction = by_id[transaction_id]
        if transaction_id in outlier_ids:
            results.append(
                UnusualTransaction(
                    transaction_id=transaction_id,
                    kind="outlier",
                    reason="Expense amount has a modified z-score above 3.5 among at least five non-recurring expenses.",
                    amount=transaction.amount,
                )
            )
        if transaction_id in duplicate_ids:
            results.append(
                UnusualTransaction(
                    transaction_id=transaction_id,
                    kind="possible_duplicate",
                    reason="Another expense has the same date, normalized merchant, and amount.",
                    amount=transaction.amount,
                )
            )
    return results


def _group_expenses(
    transactions: list[Transaction],
) -> dict[tuple[str, str, ExpenseCategory], list[Transaction]]:
    groups: dict[tuple[str, str, ExpenseCategory], list[Transaction]] = defaultdict(list)
    for transaction in transactions:
        groups[_recurrence_key(transaction)].append(transaction)
    return groups


def find_data_gaps(profile: FinancialProfile) -> list[DataGap]:
    """Report incomplete or ambiguous transaction data without inferring values."""
    gaps: list[DataGap] = []
    months = {_month(transaction) for transaction in profile.transactions}
    has_income = any(transaction.type == TransactionType.income for transaction in profile.transactions)

    for transaction in profile.transactions:
        if transaction.type == TransactionType.expense and transaction.category is None:
            gaps.append(
                DataGap(
                    transaction_id=transaction.id,
                    issue="missing_category",
                    question="What spending category best describes this expense?",
                )
            )
        if transaction.is_recurring is None:
            gaps.append(
                DataGap(
                    transaction_id=transaction.id,
                    issue="ambiguous_recurring_status",
                    question="Is this transaction recurring?",
                )
            )
        normalized_description = _normalized(transaction.description)
        if (
            normalized_description in _VAGUE_TERMS
            or len(normalized_description) < 4
            or any(term in _VAGUE_TERMS for term in normalized_description.split())
        ):
            gaps.append(
                DataGap(
                    transaction_id=transaction.id,
                    issue="vague_description",
                    question="Can you provide a more specific transaction description?",
                )
            )

    if len(months) < 2:
        gaps.append(
            DataGap(
                issue="insufficient_history",
                question="Can you provide transactions covering at least two different months?",
            )
        )
    if not has_income:
        gaps.append(
            DataGap(
                issue="no_income",
                question="Are there income transactions missing from this profile?",
            )
        )
    return gaps


def compute_expense_metrics(profile: FinancialProfile) -> ExpenseMetrics:
    """Compute summary, recurrence, unusual activity, gaps, and profile version."""
    months = sorted({_month(transaction) for transaction in profile.transactions})
    month_count = len(months)
    income_total = Decimal("0")
    category_totals: dict[ExpenseCategory, Decimal] = defaultdict(lambda: Decimal("0"))

    for transaction in profile.transactions:
        if transaction.type == TransactionType.income:
            income_total += transaction.amount.amount
        else:
            # Keep uncategorized spending in the summary while separately flagging its source data gap.
            category_totals[transaction.category or ExpenseCategory.other] += transaction.amount.amount

    rounded_categories = {
        category: Money(amount=_average(total, month_count))
        for category, total in sorted(category_totals.items(), key=lambda item: item[0].value)
    }
    monthly_expenses = sum(
        (amount.amount for amount in rounded_categories.values()), start=Decimal("0.00")
    )
    monthly_income = _average(income_total, month_count)
    available_surplus = monthly_income - monthly_expenses
    summary = FinancialSummary(
        currency=profile.currency,
        period_start=months[0],
        period_end=months[-1],
        months_covered=month_count,
        monthly_income=Money(amount=monthly_income),
        monthly_expenses=Money(amount=monthly_expenses),
        available_surplus=SignedMoney(amount=available_surplus),
        category_totals=rounded_categories,
    )
    return ExpenseMetrics(
        analysis_version=compute_version("ea", {"profile": profile.model_dump(mode="json")}),
        summary=summary,
        recurring_expenses=detect_recurring(profile),
        unusual_transactions=_detect_unusual(profile),
        data_gaps=find_data_gaps(profile),
    )