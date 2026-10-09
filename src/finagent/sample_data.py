"""Deterministic sample financial data for development and tests."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from finagent.schemas.common import ExpenseCategory, Money, SignedMoney, TransactionType
from finagent.schemas.financial import FinancialProfile, SavingsGoal, Transaction


def _d(value: str | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def sample_profile() -> FinancialProfile:
    """Three months (2026-07..2026-09), INR, salary 85_000/month, varied spending."""
    txs: list[Transaction] = [
        # --- July 2026 ---
        Transaction(
            id="inc-2026-07",
            date=date(2026, 7, 1),
            description="Salary credit",
            merchant="Employer Pvt Ltd",
            amount=Money(amount=_d(85000)),
            type=TransactionType.income,
            category=None,
            is_recurring=True,
        ),
        Transaction(
            id="exp-rent-2026-07",
            date=date(2026, 7, 3),
            description="Rent",
            merchant="Landlord",
            amount=Money(amount=_d(25000)),
            type=TransactionType.expense,
            category=ExpenseCategory.housing,
            is_recurring=True,
        ),
        Transaction(
            id="exp-groc-2026-07",
            date=date(2026, 7, 8),
            description="Groceries",
            merchant="BigBasket",
            amount=Money(amount=_d(8200)),
            type=TransactionType.expense,
            category=ExpenseCategory.groceries,
            is_recurring=False,
        ),
        Transaction(
            id="exp-util-2026-07",
            date=date(2026, 7, 10),
            description="Electricity bill",
            merchant="BESCOM",
            amount=Money(amount=_d(3100)),
            type=TransactionType.expense,
            category=ExpenseCategory.utilities,
            is_recurring=False,
        ),
        Transaction(
            id="exp-trans-2026-07",
            date=date(2026, 7, 12),
            description="Fuel and metro",
            merchant="Mixed",
            amount=Money(amount=_d(4100)),
            type=TransactionType.expense,
            category=ExpenseCategory.transport,
            is_recurring=False,
        ),
        Transaction(
            id="exp-dine-2026-07",
            date=date(2026, 7, 15),
            description="Restaurants",
            merchant="Various",
            amount=Money(amount=_d(5800)),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
            is_recurring=False,
        ),
        Transaction(
            id="exp-sub-stream-2026-07",
            date=date(2026, 7, 5),
            description="Streaming subscription",
            merchant="StreamCo",
            amount=Money(amount=_d(999)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-sub-cloud-2026-07",
            date=date(2026, 7, 6),
            description="Cloud storage",
            merchant="CloudBox",
            amount=Money(amount=_d(299)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-emi-2026-07",
            date=date(2026, 7, 7),
            description="Personal loan EMI",
            merchant="NBFC Bank",
            amount=Money(amount=_d(15000)),
            type=TransactionType.expense,
            category=ExpenseCategory.debt_payment,
            is_recurring=True,
        ),
        Transaction(
            id="exp-electronics-2026-07",
            date=date(2026, 7, 20),
            description="Laptop purchase",
            merchant="ElectroMart",
            amount=Money(amount=_d(38000)),
            type=TransactionType.expense,
            category=ExpenseCategory.shopping,
            is_recurring=False,
        ),
        Transaction(
            id="exp-misc-2026-07",
            date=date(2026, 7, 22),
            description="ATM withdrawal usage unclear",
            merchant="ATM",
            amount=Money(amount=_d(1200)),
            type=TransactionType.expense,
            category=None,
            is_recurring=None,
        ),
        # --- August 2026 ---
        Transaction(
            id="inc-2026-08",
            date=date(2026, 8, 1),
            description="Salary credit",
            merchant="Employer Pvt Ltd",
            amount=Money(amount=_d(85000)),
            type=TransactionType.income,
            category=None,
            is_recurring=True,
        ),
        Transaction(
            id="exp-rent-2026-08",
            date=date(2026, 8, 3),
            description="Rent",
            merchant="Landlord",
            amount=Money(amount=_d(25000)),
            type=TransactionType.expense,
            category=ExpenseCategory.housing,
            is_recurring=True,
        ),
        Transaction(
            id="exp-groc-2026-08",
            date=date(2026, 8, 9),
            description="Groceries",
            merchant="BigBasket",
            amount=Money(amount=_d(9100)),
            type=TransactionType.expense,
            category=ExpenseCategory.groceries,
            is_recurring=False,
        ),
        Transaction(
            id="exp-util-2026-08",
            date=date(2026, 8, 11),
            description="Electricity bill",
            merchant="BESCOM",
            amount=Money(amount=_d(3400)),
            type=TransactionType.expense,
            category=ExpenseCategory.utilities,
            is_recurring=False,
        ),
        Transaction(
            id="exp-trans-2026-08",
            date=date(2026, 8, 13),
            description="Fuel and metro",
            merchant="Mixed",
            amount=Money(amount=_d(3900)),
            type=TransactionType.expense,
            category=ExpenseCategory.transport,
            is_recurring=False,
        ),
        Transaction(
            id="exp-dine-2026-08-main",
            date=date(2026, 8, 16),
            description="Restaurants",
            merchant="Various",
            amount=Money(amount=_d(5200)),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
            is_recurring=False,
        ),
        Transaction(
            id="exp-dine-dup-a",
            date=date(2026, 8, 15),
            description="Food delivery",
            merchant="Swiggy",
            amount=Money(amount=_d(450)),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
            is_recurring=False,
        ),
        Transaction(
            id="exp-dine-dup-b",
            date=date(2026, 8, 15),
            description="Food delivery",
            merchant="Swiggy",
            amount=Money(amount=_d(450)),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
            is_recurring=False,
        ),
        Transaction(
            id="exp-sub-stream-2026-08",
            date=date(2026, 8, 5),
            description="Streaming subscription",
            merchant="StreamCo",
            amount=Money(amount=_d(999)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-sub-cloud-2026-08",
            date=date(2026, 8, 6),
            description="Cloud storage",
            merchant="CloudBox",
            amount=Money(amount=_d(299)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-emi-2026-08",
            date=date(2026, 8, 7),
            description="Personal loan EMI",
            merchant="NBFC Bank",
            amount=Money(amount=_d(15000)),
            type=TransactionType.expense,
            category=ExpenseCategory.debt_payment,
            is_recurring=True,
        ),
        Transaction(
            id="exp-misc-2026-08",
            date=date(2026, 8, 25),
            description="Uncategorized UPI",
            merchant="UPI",
            amount=Money(amount=_d(800)),
            type=TransactionType.expense,
            category=None,
            is_recurring=False,
        ),
        # --- September 2026 ---
        Transaction(
            id="inc-2026-09",
            date=date(2026, 9, 1),
            description="Salary credit",
            merchant="Employer Pvt Ltd",
            amount=Money(amount=_d(85000)),
            type=TransactionType.income,
            category=None,
            is_recurring=True,
        ),
        Transaction(
            id="exp-rent-2026-09",
            date=date(2026, 9, 3),
            description="Rent",
            merchant="Landlord",
            amount=Money(amount=_d(25000)),
            type=TransactionType.expense,
            category=ExpenseCategory.housing,
            is_recurring=True,
        ),
        Transaction(
            id="exp-groc-2026-09",
            date=date(2026, 9, 8),
            description="Groceries",
            merchant="BigBasket",
            amount=Money(amount=_d(7600)),
            type=TransactionType.expense,
            category=ExpenseCategory.groceries,
            is_recurring=False,
        ),
        Transaction(
            id="exp-util-2026-09",
            date=date(2026, 9, 10),
            description="Electricity bill",
            merchant="BESCOM",
            amount=Money(amount=_d(2900)),
            type=TransactionType.expense,
            category=ExpenseCategory.utilities,
            is_recurring=False,
        ),
        Transaction(
            id="exp-trans-2026-09",
            date=date(2026, 9, 12),
            description="Fuel and metro",
            merchant="Mixed",
            amount=Money(amount=_d(4300)),
            type=TransactionType.expense,
            category=ExpenseCategory.transport,
            is_recurring=False,
        ),
        Transaction(
            id="exp-dine-2026-09",
            date=date(2026, 9, 18),
            description="Restaurants",
            merchant="Various",
            amount=Money(amount=_d(6400)),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
            is_recurring=False,
        ),
        Transaction(
            id="exp-sub-stream-2026-09",
            date=date(2026, 9, 5),
            description="Streaming subscription",
            merchant="StreamCo",
            amount=Money(amount=_d(999)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-sub-cloud-2026-09",
            date=date(2026, 9, 6),
            description="Cloud storage",
            merchant="CloudBox",
            amount=Money(amount=_d(299)),
            type=TransactionType.expense,
            category=ExpenseCategory.subscriptions,
            is_recurring=True,
        ),
        Transaction(
            id="exp-emi-2026-09",
            date=date(2026, 9, 7),
            description="Personal loan EMI",
            merchant="NBFC Bank",
            amount=Money(amount=_d(15000)),
            type=TransactionType.expense,
            category=ExpenseCategory.debt_payment,
            is_recurring=True,
        ),
    ]
    return FinancialProfile(profile_id="sample-inr-2026-q3", currency="INR", transactions=txs)


def sample_savings_goal_feasible() -> SavingsGoal:
    """15_000/month target — achievable after trimming discretionary spend (see ``verify_sample_data``)."""
    return SavingsGoal(monthly_target=Money(amount=_d(15000)))


def sample_savings_goal_infeasible() -> SavingsGoal:
    """50_000/month target — exceeds income after essential obligations."""
    return SavingsGoal(monthly_target=Money(amount=_d(50000)))


def sample_research_question() -> str:
    """Educational research question (India context)."""
    return (
        "For a retail investor in India, how do SIP installments in equity mutual funds "
        "compare with a one-time lump-sum investment over a 5–10 year horizon, and what "
        "role do RBI repo-rate changes play in fixed-deposit returns?"
    )


def profile_monthly_averages(profile: FinancialProfile) -> tuple[Decimal, Decimal, Decimal]:
    """Return ``(monthly_income, monthly_expenses, available_surplus)`` averages.

    Expenses with ``category is None`` are included in monthly expenses but omitted
    from category rollups (mirrors pre-analysis profiles).
    """
    months = sorted({f"{t.date.year:04d}-{t.date.month:02d}" for t in profile.transactions})
    if not months:
        raise ValueError("profile has no transactions")

    income_by_month: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    expense_by_month: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for t in profile.transactions:
        key = f"{t.date.year:04d}-{t.date.month:02d}"
        if t.type == TransactionType.income:
            income_by_month[key] += t.amount.amount
        else:
            expense_by_month[key] += t.amount.amount

    n = Decimal(len(months))
    total_income = sum(income_by_month[m] for m in months)
    total_expense = sum(expense_by_month[m] for m in months)
    monthly_income = (total_income / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    monthly_expenses = (total_expense / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    surplus = (monthly_income - monthly_expenses).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return monthly_income, monthly_expenses, SignedMoney(amount=surplus).amount


def max_achievable_monthly_savings(profile: FinancialProfile) -> Decimal:
    """Upper bound savings if recurring essentials stay and one-off outlier is excluded."""
    monthly_income, _, _ = profile_monthly_averages(profile)
    essential_floor = Decimal("0")
    for t in profile.transactions:
        if t.type != TransactionType.expense:
            continue
        if t.is_recurring is True or t.category in (
            ExpenseCategory.housing,
            ExpenseCategory.debt_payment,
            ExpenseCategory.utilities,
        ):
            essential_floor += t.amount.amount
        elif t.id == "exp-electronics-2026-07":
            continue
        elif t.category is None:
            essential_floor += t.amount.amount
    months = Decimal(3)
    essential_avg = (essential_floor / months).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (monthly_income - essential_avg).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def verify_sample_data() -> None:
    """Validate sample profile and savings-goal feasibility claims (raises on mismatch)."""
    profile = sample_profile()
    FinancialProfile.model_validate(profile.model_dump())

    income, expenses, surplus = profile_monthly_averages(profile)
    assert income == _d(85000)
    assert expenses == _d(76264.67)
    assert surplus == _d(8735.33)

    feasible = sample_savings_goal_feasible().monthly_target
    assert feasible is not None
    max_save = max_achievable_monthly_savings(profile)
    assert max_save >= feasible.amount, "feasible goal should be within max achievable savings"
    assert surplus < feasible.amount, "feasible goal should require some spending cuts"

    infeasible = sample_savings_goal_infeasible().monthly_target
    assert infeasible is not None
    assert infeasible.amount > max_save, "infeasible goal should exceed max achievable monthly savings"
