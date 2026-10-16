"""Core financial profile and summary models."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from finagent.schemas.common import (
    ExpenseCategory,
    Money,
    SignedMoney,
    TransactionType,
    validate_currency_code,
    validate_month,
)


class Transaction(BaseModel):
    """Single income or expense line item."""

    model_config = ConfigDict(extra="forbid")

    id: str
    date: date
    description: str
    merchant: str | None = None
    amount: Money
    type: TransactionType
    category: ExpenseCategory | None = None
    is_recurring: bool | None = None

    @model_validator(mode="after")
    def _positive_amount(self) -> Transaction:
        if self.amount.amount <= 0:
            raise ValueError("transaction amount must be greater than zero")
        return self


class SavingsGoal(BaseModel):
    """Savings intent: fixed monthly target or target rate of income."""

    model_config = ConfigDict(extra="forbid")

    monthly_target: Money | None = None
    target_rate: Annotated[Decimal | None, Field(description="Fraction in (0, 1] of income")] = None

    @field_validator("target_rate", mode="before")
    @classmethod
    def _reject_float_rate(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("float target_rate is not allowed; use str or Decimal")
        return value

    @model_validator(mode="after")
    def _exactly_one_target(self) -> SavingsGoal:
        has_amount = self.monthly_target is not None
        has_rate = self.target_rate is not None
        if has_amount == has_rate:
            raise ValueError("set exactly one of monthly_target or target_rate")
        if self.target_rate is not None:
            if self.target_rate <= 0 or self.target_rate > 1:
                raise ValueError("target_rate must be in (0, 1]")
        return self


class FinancialProfile(BaseModel):
    """Input profile for analysis agents."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    currency: str = "INR"
    transactions: list[Transaction] = Field(..., min_length=1)
    savings_goal: SavingsGoal | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency_code(value)

    @model_validator(mode="after")
    def _unique_transaction_ids(self) -> FinancialProfile:
        ids = [t.id for t in self.transactions]
        if len(ids) != len(set(ids)):
            raise ValueError("transaction ids must be unique")
        return self


class FinancialSummary(BaseModel):
    """Monthly averages plus explicitly named whole-period cash-flow totals."""

    model_config = ConfigDict(extra="forbid")

    currency: str
    period_start: str
    period_end: str
    months_covered: int = Field(..., ge=1)
    monthly_income: Money
    monthly_expenses: Money
    available_surplus: SignedMoney
    category_totals: dict[ExpenseCategory, Money]
    # Cash received includes refunds, which are also identified separately.
    # Transfers between owned accounts never count as income or spending.
    received_total: Money | None = None
    spent_total: Money | None = None
    refund_total: Money | None = None
    transaction_count: int | None = Field(default=None, ge=0)
    monthly_breakdown: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return validate_currency_code(value)

    @field_validator("period_start", "period_end")
    @classmethod
    def _month(cls, value: str) -> str:
        return validate_month(value)

    @model_validator(mode="after")
    def _consistent_totals(self) -> FinancialSummary:
        cat_sum = sum((m.amount for m in self.category_totals.values()), start=Decimal("0"))
        cat_sum = cat_sum.quantize(Decimal("0.01"))
        if cat_sum != self.monthly_expenses.amount:
            raise ValueError("monthly_expenses must equal sum of category_totals")
        surplus = self.monthly_income.amount - self.monthly_expenses.amount
        surplus = surplus.quantize(Decimal("0.01"))
        if surplus != self.available_surplus.amount:
            raise ValueError("available_surplus must equal monthly_income - monthly_expenses")
        return self
