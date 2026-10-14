"""Run expense analysis against the bundled sample profile."""

from __future__ import annotations

import argparse
import json

from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.agents.expense_analysis.graph import run_expense_analysis
from finagent.sample_data import sample_profile
from finagent.schemas.common import AgentStatus
from finagent.schemas.expense import ExpenseAnalysisResult


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the bundled FinAgent sample profile.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Run only deterministic calculations; do not initialize a language model.",
    )
    args = parser.parse_args()
    profile = sample_profile()

    if args.no_llm:
        metrics = compute_expense_metrics(profile)
        result = ExpenseAnalysisResult(
            status=AgentStatus.success,
            analysis_version=metrics.analysis_version,
            summary=metrics.summary,
            recurring_expenses=metrics.recurring_expenses,
            unusual_transactions=metrics.unusual_transactions,
            data_gaps=metrics.data_gaps,
        )
        mode = "deterministic_only"
    else:
        result = run_expense_analysis({"profile": profile.model_dump(mode="json")})
        mode = "llm_assisted"

    print(json.dumps({"mode": mode, "result": result.model_dump(mode="json")}, indent=2))


if __name__ == "__main__":
    main()