"""Structured LLM contract for bounded budget suggestions."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field

from finagent.schemas.common import ExpenseCategory, Money


class ProposedCategoryLimit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ExpenseCategory
    monthly_limit: Money
    rationale: str


class BudgetProposal(BaseModel):
    """Only bounded discretionary suggestions may be supplied by the LLM."""

    model_config = ConfigDict(extra="forbid")

    category_adjustments: list[ProposedCategoryLimit] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the optional proposal step in a deterministic budgeting system.
Suggest a monthly limit for every listed discretionary category, choosing only an amount
within its supplied floor and current-spend bounds. Do not change essential categories,
add categories, or exceed the savings target's available budget. Give a concise rationale
for each category. Return only the requested structured fields: category_adjustments,
assumptions, and trade_offs. Do not recalculate the supplied expense analysis."""


def proposal_prompt(
    *,
    currency: str,
    income: str,
    target: str,
    categories: list[dict[str, str]],
) -> str:
    """Serialize verified deterministic bounds for a structured proposal."""
    return (
        "Propose limits using only these categories and bounds.\n"
        f"Currency: {currency}\nMonthly income: {income}\n"
        f"Requested monthly savings: {target}\n"
        f"Discretionary categories: {json.dumps(categories, sort_keys=True)}"
    )
