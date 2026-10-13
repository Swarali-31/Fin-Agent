"""Structured qualitative composition contract for financial reports."""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field


class ReportComposition(BaseModel):
    """Qualitative narrative fields; all numeric/source data is copied elsewhere."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    spending_insights: list[str] = Field(default_factory=list)
    savings_opportunities: list[str] = Field(default_factory=list)
    risk_considerations: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """Compose a concise financial report using only the supplied
upstream analysis, budget, and research content. The fields you return are qualitative
prose only: summary, spending_insights, savings_opportunities, and risk_considerations.
Do not include or calculate any numbers, currency amounts, percentages, dates, or
quantities. Do not write URLs or source identifiers in narrative text. Do not change
figures, budget values, research findings, source metadata, or assumptions. Do not offer
personalized investment advice. Keep all language consistent with the supplied evidence."""


def composition_prompt(context: dict[str, object]) -> str:
    return "Compose the qualitative report text from this data:\n" + json.dumps(
        context,
        sort_keys=True,
        default=str,
    )
