from __future__ import annotations

from decimal import Decimal
from datetime import UTC, datetime

from finagent.agents.budget_planning.graph import run_budget_planning
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.agents.financial_report.validation import (
    validate_report_request,
    validation_status,
    validation_summary,
)
from finagent.sample_data import sample_profile, sample_savings_goal_feasible
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    SignedMoney,
    SourceTier,
    Severity,
    ValidationStatus,
)
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.report import ReportRequest
from finagent.schemas.research import ResearchFinding, ResearchResult, SourceMetadata


def _analysis() -> ExpenseAnalysisResult:
    profile = sample_profile().model_copy(deep=True)
    for transaction in profile.transactions:
        if transaction.type.value == "expense":
            if transaction.category is None:
                transaction.category = ExpenseCategory.other
            if transaction.is_recurring is None:
                transaction.is_recurring = False
    transaction = next(
        item for item in profile.transactions if item.id == "exp-misc-2026-07"
    )
    transaction.description = "Cash withdrawal"
    metrics = compute_expense_metrics(profile)
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
        data_gaps=[],
        spending_patterns=[],
    )


def _research() -> ResearchResult:
    return ResearchResult(
        status=AgentStatus.success,
        question="TEST FIXTURE: educational investing question",
        findings=[
            ResearchFinding(
                statement="TEST FIXTURE: diversification is an educational concept.",
                source_ids=["S1"],
                confidence="medium",
            )
        ],
        sources=[
            SourceMetadata(
                source_id="S1",
                title="TEST FIXTURE - synthetic investor education",
                url="https://education.example.invalid/guide",
                publisher="example.invalid",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                tier=SourceTier.other,
                snippet="TEST FIXTURE: synthetic content only.",
            )
        ],
        search_provider="synthetic-test-fixture",
    )


def _request() -> ReportRequest:
    analysis = _analysis()
    budget = run_budget_planning(
        BudgetRequest(
            expense_analysis=analysis,
            savings_goal=sample_savings_goal_feasible(),
        ),
        llm=False,
    )
    return ReportRequest(expense_analysis=analysis, budget=budget, research=_research())


def test_consistent_inputs_are_valid() -> None:
    request = _request()

    issues = validate_report_request(request)

    assert issues == []
    assert validation_status(issues) == ValidationStatus.valid
    assert "Valid:" in validation_summary(issues)


def test_stale_budget_is_an_error_and_summary_names_code() -> None:
    request = _request()
    stale_budget = request.budget.model_copy(
        update={"source_analysis_version": "ea-stale000000"}
    )
    request = request.model_copy(update={"budget": stale_budget})

    issues = validate_report_request(request)

    assert any(
        issue.code == "STALE_BUDGET" and issue.severity == Severity.error
        for issue in issues
    )
    assert "STALE_BUDGET" in validation_summary(issues)
    assert validation_status(issues) == ValidationStatus.rejected


def test_expected_analysis_version_mismatch_is_an_error() -> None:
    request = _request().model_copy(
        update={"expected_analysis_version": "ea-different"}
    )

    issues = validate_report_request(request)

    assert any(issue.code == "STALE_ANALYSIS" for issue in issues)


def test_currency_mismatch_is_an_error() -> None:
    request = _request()
    request = request.model_copy(
        update={"budget": request.budget.model_copy(update={"currency": "USD"})}
    )

    issues = validate_report_request(request)

    assert any(issue.code == "CURRENCY_MISMATCH" for issue in issues)


def test_budget_current_spending_mismatch_is_period_error() -> None:
    request = _request()
    first = request.budget.category_limits[0]
    changed = first.model_copy(
        update={"current_monthly_spend": Money(amount=first.current_monthly_spend.amount + 1)}
    )
    budget = request.budget.model_copy(
        update={
            "category_limits": [changed, *request.budget.category_limits[1:]]
        }
    )

    issues = validate_report_request(request.model_copy(update={"budget": budget}))

    assert any(issue.code == "PERIOD_MISMATCH" for issue in issues)


def test_arithmetic_inconsistency_is_an_error() -> None:
    request = _request()
    summary = request.expense_analysis.summary
    assert summary is not None
    summary = summary.model_copy(
        update={"available_surplus": SignedMoney(amount=Decimal("1.00"))}
    )
    analysis = request.expense_analysis.model_copy(update={"summary": summary})
    issues = validate_report_request(
        request.model_copy(update={"expense_analysis": analysis})
    )

    assert any(issue.code == "SURPLUS_INCONSISTENT" for issue in issues)
