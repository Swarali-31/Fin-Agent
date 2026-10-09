"""Expense analysis agent I/O models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from finagent.schemas.common import AgentName, AgentResultBase, ExpenseCategory, Money
from finagent.schemas.financial import FinancialProfile, FinancialSummary


class RecurringExpense(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    category: ExpenseCategory
    monthly_amount: Money
    occurrences: int = Field(..., ge=1)


class UnusualTransaction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    kind: str = Field(..., pattern="^(outlier|possible_duplicate)$")
    reason: str
    amount: Money


class SpendingInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    categories: list[ExpenseCategory] = Field(default_factory=list)


class DataGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str | None = None
    issue: str
    question: str


class ExpenseAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: FinancialProfile


class ExpenseAnalysisResult(AgentResultBase):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName = AgentName.expense_analysis
    analysis_version: str | None = None
    summary: FinancialSummary | None = None
    recurring_expenses: list[RecurringExpense] = Field(default_factory=list)
    unusual_transactions: list[UnusualTransaction] = Field(default_factory=list)
    spending_patterns: list[SpendingInsight] = Field(default_factory=list)
    data_gaps: list[DataGap] = Field(default_factory=list)
