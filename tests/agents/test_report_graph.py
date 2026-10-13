from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from finagent.agents.budget_planning.graph import run_budget_planning
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
from finagent.agents.financial_report.graph import run_financial_report
from finagent.sample_data import (
    sample_profile,
    sample_savings_goal_feasible,
    sample_savings_goal_infeasible,
)
from finagent.schemas.budget import BudgetRequest
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    SourceTier,
    ValidationStatus,
)
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import Transaction
from finagent.schemas.report import ReportRequest
from finagent.schemas.research import (
    ResearchFinding,
    ResearchResult,
    SourceMetadata,
)


def _analysis(changed: bool = False) -> ExpenseAnalysisResult:
    profile = sample_profile().model_copy(deep=True)
    for transaction in profile.transactions:
        if transaction.type.value == "expense":
            if transaction.category is None:
                transaction.category = ExpenseCategory.other
            if transaction.is_recurring is None:
                transaction.is_recurring = False
    misc = next(item for item in profile.transactions if item.id == "exp-misc-2026-07")
    misc.description = "Cash withdrawal"
    if changed:
        profile.transactions.append(
            Transaction(
                id="exp-report-change",
                date=misc.date,
                description="New grocery purchase",
                amount=Money(amount="75.25"),
                type="expense",
                category=ExpenseCategory.groceries,
                is_recurring=False,
            )
        )
    metrics = compute_expense_metrics(profile)
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version=metrics.analysis_version,
        summary=metrics.summary,
        recurring_expenses=metrics.recurring_expenses,
        unusual_transactions=metrics.unusual_transactions,
        spending_patterns=[],
        data_gaps=[],
    )


def _research(
    *,
    status: AgentStatus = AgentStatus.success,
    statement: str = "TEST FIXTURE: diversification is an educational risk concept.",
) -> ResearchResult:
    source = SourceMetadata(
        source_id="S1",
        title="TEST FIXTURE - synthetic investor education",
        url="https://education.example.invalid/guide",
        publisher="example.invalid",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        tier=SourceTier.other,
        snippet="TEST FIXTURE: synthetic content only.",
    )
    findings = (
        [
            ResearchFinding(
                statement=statement,
                source_ids=["S1"],
                confidence="medium",
            )
        ]
        if status == AgentStatus.success
        else []
    )
    return ResearchResult(
        status=status,
        question="TEST FIXTURE: educational question",
        findings=findings,
        sources=[source] if status != AgentStatus.failed else [],
        search_provider="synthetic-test-fixture",
    )


def _request(
    *,
    changed_analysis: bool = False,
    savings_goal: Any = None,
    research: ResearchResult | None = None,
) -> ReportRequest:
    analysis = _analysis(changed_analysis)
    budget = run_budget_planning(
        BudgetRequest(
            expense_analysis=analysis,
            savings_goal=savings_goal or sample_savings_goal_feasible(),
        ),
        llm=False,
    )
    return ReportRequest(
        expense_analysis=analysis,
        budget=budget,
        research=research if research is not None else _research(),
    )


class SyntheticReportModel:
    """Test-only fake structured output with no network access."""

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response or {
            "summary": "The supplied information supports a high-level financial overview.",
            "spending_insights": ["The supplied categories show different spending patterns."],
            "savings_opportunities": ["Review flexible spending against the supplied plan."],
            "risk_considerations": ["Interpret the findings alongside the supplied limitations."],
        }
        self.error = error

    def with_structured_output(self, schema: type) -> SyntheticReportModel:
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if self.error:
            raise self.error
        return self.response


def test_valid_path_copies_upstream_values_without_rewriting_numbers() -> None:
    request = _request()
    report = run_financial_report(request, llm=SyntheticReportModel())

    assert report.status == AgentStatus.success
    assert report.validation_status == ValidationStatus.valid
    assert report.report_version
    assert report.source_versions is not None
    assert report.source_versions.analysis_version == request.expense_analysis.analysis_version
    assert report.source_versions.budget_id == request.budget.budget_id
    assert report.sections is not None
    assert report.sections.budget_overview == request.budget.category_limits
    assert report.sections.research_findings == request.research.findings
    assert report.sections.sources == request.research.sources
    assert report.sections.assumptions == request.budget.assumptions
    for report_category, upstream_category in zip(
        report.sections.budget_overview,
        request.budget.category_limits,
        strict=True,
    ):
        assert report_category.monthly_limit.amount == upstream_category.monthly_limit.amount
        assert (
            report_category.current_monthly_spend.amount
            == upstream_category.current_monthly_spend.amount
        )
    assert "85000" not in report.sections.summary
    assert "15000" not in report.sections.summary


def test_stale_budget_rejected_without_sections() -> None:
    request = _request()
    new_analysis = _analysis(changed=True)
    stale_request = request.model_copy(
        update={"expense_analysis": new_analysis}
    )

    report = run_financial_report(stale_request, llm=SyntheticReportModel())

    assert report.status == AgentStatus.failed
    assert report.validation_status == ValidationStatus.rejected
    assert report.sections is None
    assert report.report_version is None
    assert "STALE_BUDGET" in report.validation_summary


def test_expected_version_mismatch_rejected() -> None:
    request = _request().model_copy(
        update={"expected_analysis_version": "ea-other"}
    )

    report = run_financial_report(request, llm=SyntheticReportModel())

    assert report.validation_status == ValidationStatus.rejected
    assert report.sections is None
    assert "STALE_ANALYSIS" in report.validation_summary


def test_currency_mismatch_rejected() -> None:
    request = _request()
    request = request.model_copy(
        update={"budget": request.budget.model_copy(update={"currency": "USD"})}
    )

    report = run_financial_report(request, llm=SyntheticReportModel())

    assert report.validation_status == ValidationStatus.rejected
    assert report.sections is None
    assert "CURRENCY_MISMATCH" in report.validation_summary


def test_missing_or_failed_research_is_flagged_but_report_is_produced() -> None:
    missing = _request().model_copy(update={"research": None})
    failed = _request(research=_research(status=AgentStatus.failed))

    missing_report = run_financial_report(missing, llm=SyntheticReportModel())
    failed_report = run_financial_report(failed, llm=SyntheticReportModel())

    assert missing_report.status == AgentStatus.partial
    assert missing_report.validation_status == ValidationStatus.flagged
    assert missing_report.sections is not None
    assert any(issue.code == "RESEARCH_MISSING" for issue in missing_report.validation_issues)
    assert failed_report.status == AgentStatus.partial
    assert failed_report.sections is not None
    assert any(issue.code == "RESEARCH_FAILED" for issue in failed_report.validation_issues)


def test_infeasible_budget_is_flagged() -> None:
    request = _request(savings_goal=sample_savings_goal_infeasible())

    report = run_financial_report(request, llm=SyntheticReportModel())

    assert report.validation_status == ValidationStatus.flagged
    assert report.status == AgentStatus.partial
    assert any(issue.code == "INFEASIBLE_SAVINGS" for issue in report.validation_issues)
    assert report.sections is not None


def test_same_inputs_produce_same_report_version() -> None:
    request = _request()

    first = run_financial_report(request, llm=SyntheticReportModel())
    second = run_financial_report(request, llm=SyntheticReportModel())

    assert first.report_version == second.report_version


def test_llm_failure_uses_deterministic_template_summary() -> None:
    report = run_financial_report(
        _request(),
        llm=SyntheticReportModel(error=RuntimeError("synthetic model unavailable")),
    )

    assert report.status == AgentStatus.partial
    assert report.sections is not None
    assert "supplied financial analysis" in report.sections.summary
    assert any(
        limitation.code == "llm_composition_unavailable"
        for limitation in report.limitations
    )


def test_no_llm_mode_uses_deterministic_template_without_failure_limitation() -> None:
    report = run_financial_report(_request(), llm=False)

    assert report.sections is not None
    assert "supplied financial analysis" in report.sections.summary
    assert not any(
        limitation.code == "llm_composition_unavailable"
        for limitation in report.limitations
    )


def test_llm_invented_url_and_source_reference_are_removed() -> None:
    model = SyntheticReportModel(
        {
            "summary": (
                "Review the concepts [S99] at https://invented.example.invalid/advice. "
                "The supplied research [S1] may provide context."
            ),
            "spending_insights": [],
            "savings_opportunities": [],
            "risk_considerations": [],
        }
    )

    report = run_financial_report(_request(), llm=model)

    assert report.sections is not None
    assert "invented.example.invalid" not in report.sections.summary
    assert "S99" not in report.sections.summary
    assert "https://education.example.invalid/guide" not in report.sections.summary
    assert "S1" in report.sections.summary
