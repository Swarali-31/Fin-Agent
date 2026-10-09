"""Budget planning agent I/O models."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finagent.schemas.common import AgentName, AgentResultBase, ExpenseCategory, Money
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import SavingsGoal


class BudgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_analysis: ExpenseAnalysisResult
    savings_goal: SavingsGoal | None = None
    essential_categories: list[ExpenseCategory] | None = None


class CategoryBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ExpenseCategory
    monthly_limit: Money
    current_monthly_spend: Money
    is_essential: bool
    rationale: str


class Feasibility(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_feasible: bool
    requested_monthly_savings: Money
    max_achievable_monthly_savings: Money
    shortfall: Money
    suggestions: list[str] = Field(default_factory=list)


class RevisionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_budget_id: str
    previous_source_analysis_version: str
    changes: list[str] = Field(default_factory=list)


class BudgetPlan(AgentResultBase):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName = AgentName.budget_planning
    budget_id: str | None = None
    revision: int = Field(default=1, ge=1)
    source_analysis_version: str | None = None
    currency: str
    monthly_income: Money
    category_limits: list[CategoryBudget] = Field(default_factory=list)
    planned_monthly_savings: Money
    feasibility: Feasibility
    assumptions: list[str] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    revision_info: RevisionInfo | None = None

    @model_validator(mode="after")
    def _within_income(self) -> BudgetPlan:
        total_limits = sum((c.monthly_limit.amount for c in self.category_limits), start=Decimal("0"))
        total = total_limits + self.planned_monthly_savings.amount
        total = total.quantize(Decimal("0.01"))
        if total > self.monthly_income.amount:
            raise ValueError("sum of category limits and planned savings must not exceed monthly_income")
        return self
