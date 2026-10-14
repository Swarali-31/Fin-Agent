"""Run valid and stale-input financial report scenarios."""

from __future__ import annotations

import argparse
import json

from finagent.agents.budget_planning.graph import run_budget_planning
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.agents.financial_report.graph import run_financial_report
from finagent.sample_data import sample_profile, sample_savings_goal_feasible
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import AgentStatus, ExpenseCategory, Money, TransactionType
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, Transaction
from finagent.schemas.report import ReportRequest


def _analysis(profile: FinancialProfile) -> ExpenseAnalysisResult:
    metrics = compute_expense_metrics(profile)
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
        recurring_expenses=metrics.recurring_expenses,
        unusual_transactions=metrics.unusual_transactions,
        spending_patterns=[],
        data_gaps=metrics.data_gaps,
    )


def _profile_without_open_gaps() -> FinancialProfile:
    profile = sample_profile()
    for transaction in profile.transactions:
        if transaction.type == TransactionType.expense and transaction.category is None:
            transaction.category = ExpenseCategory.other
        if transaction.is_recurring is None:
            transaction.is_recurring = False
    misc = next(item for item in profile.transactions if item.id == "exp-misc-2026-07")
    misc.description = "Cash withdrawal"
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sample financial report scenarios.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use deterministic report composition without initializing an LLM.",
    )
    args = parser.parse_args()
    llm = False if args.no_llm else None

    profile = _profile_without_open_gaps()
    analysis = _analysis(profile)
    budget = run_budget_planning(
        BudgetRequest(
            expense_analysis=analysis,
            savings_goal=sample_savings_goal_feasible(),
        ),
        llm=False,
    )
    valid_report = run_financial_report(
        ReportRequest(expense_analysis=analysis, budget=budget),
        llm=llm,
    )

    changed_profile = profile.model_copy(deep=True)
    changed_profile.transactions.append(
        Transaction(
            id="exp-report-example-change",
            date=changed_profile.transactions[-1].date,
            description="Additional grocery purchase",
            amount=Money(amount="75.25"),
            type=TransactionType.expense,
            category=ExpenseCategory.groceries,
            is_recurring=False,
        )
    )
    stale_analysis = _analysis(changed_profile)
    stale_report = run_financial_report(
        ReportRequest(
            expense_analysis=stale_analysis,
            budget=budget,
        ),
        llm=llm,
    )

    print(
        json.dumps(
            {
                "mode": "deterministic_fallback" if args.no_llm else "llm_composition",
                "consistent_inputs_scenario": valid_report.model_dump(mode="json"),
                "stale_scenario": stale_report.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
