"""Run feasible, infeasible, and revised budgets on the bundled profile."""

from __future__ import annotations

import argparse
import json
from datetime import date

from finagent.agents.budget_planning.graph import revise_budget, run_budget_planning
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.sample_data import (
    sample_profile,
    sample_savings_goal_feasible,
    sample_savings_goal_infeasible,
)
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import AgentStatus, ExpenseCategory, Money, TransactionType
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, Transaction


def _analysis(profile: FinancialProfile) -> ExpenseAnalysisResult:
    metrics = compute_expense_metrics(profile)
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run sample budget planning scenarios.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use only the deterministic baseline; do not initialize a language model.",
    )
    args = parser.parse_args()
    llm = False if args.no_llm else None
    profile = sample_profile()
    analysis = _analysis(profile)

    feasible = run_budget_planning(
        BudgetRequest(
            expense_analysis=analysis,
            savings_goal=sample_savings_goal_feasible(),
        ),
        llm=llm,
    )
    infeasible = run_budget_planning(
        BudgetRequest(
            expense_analysis=analysis,
            savings_goal=sample_savings_goal_infeasible(),
        ),
        llm=llm,
    )

    changed_profile = profile.model_copy(deep=True)
    changed_profile.transactions.append(
        Transaction(
            id="exp-profile-change",
            date=date(2026, 9, 25),
            description="Restaurants",
            amount=Money(amount="12000.00"),
            type=TransactionType.expense,
            category=ExpenseCategory.dining,
        )
    )
    revised = revise_budget(feasible, _analysis(changed_profile), llm=llm)

    print(
        json.dumps(
            {
                "mode": "deterministic_only" if args.no_llm else "llm_assisted",
                "feasible_goal": feasible.model_dump(mode="json"),
                "infeasible_goal": infeasible.model_dump(mode="json"),
                "after_profile_change": revised.model_dump(mode="json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
