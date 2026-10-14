"""Structured qualitative interpretation contract for expense analysis."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InterpretationInsight(BaseModel):
    """Internal LLM insight with references that can be verified before output."""

    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str
    categories: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)


class ExpenseInterpretation(BaseModel):
    """The only fields the LLM may contribute to an expense analysis."""

    model_config = ConfigDict(extra="forbid")

    spending_patterns: list[InterpretationInsight] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the qualitative interpretation step of a personal expense analysis.
Use only the computed metrics supplied by the deterministic system. Do not calculate,
infer, or restate amounts, counts, dates, averages, percentages, or other numeric values.
Do not make budgets, financial recommendations, research claims, or report prose. Return
only qualitative spending_patterns and clarifying_questions. Categories and transaction
IDs must be copied exactly from the supplied allowed lists; omit references you cannot
support. Keep insights concise and grounded in the supplied metrics."""


def interpretation_prompt(metrics: dict[str, object]) -> str:
    """Format computed data plus reference allow-lists for the structured model."""
    import json

    allowed_categories = metrics.get("categories", [])
    allowed_transaction_ids = metrics.get("transaction_ids", [])
    return (
        "Interpret these already-computed expense metrics qualitatively. Do not produce "
        "new or repeated numeric values.\n\n"
        f"Computed metrics: {json.dumps(metrics, sort_keys=True, default=str)}\n\n"
        f"Allowed categories: {json.dumps(allowed_categories)}\n"
        f"Allowed transaction IDs: {json.dumps(allowed_transaction_ids)}"
    )