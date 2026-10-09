"""Tests for FinAgent Pydantic schemas."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finagent.schemas.budget import BudgetPlan, BudgetRequest, CategoryBudget, Feasibility
from finagent.schemas.common import (
    AgentName,
    AgentStatus,
    ExpenseCategory,
    Money,
    SignedMoney,
    SourceTier,
    ValidationStatus,
    compute_version,
)
from finagent.schemas.expense import ExpenseAnalysisRequest, ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, FinancialSummary, SavingsGoal, Transaction
from finagent.schemas.report import FinancialReport, ReportRequest, ReportSections, ReportSourceVersions
from finagent.schemas.research import ResearchFinding, ResearchRequest, ResearchResult, SourceMetadata
from finagent.sample_data import sample_profile


def test_money_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Money(amount=1.5)


def test_money_decimal_precision_half_up() -> None:
    m = Money(amount=Decimal("0.1") + Decimal("0.2"))
    assert m.amount == Decimal("0.30")
    assert m.model_dump()["amount"] == Decimal("0.30")
    dumped = m.model_dump(mode="json")
    assert dumped["amount"] == "0.30"


def test_money_accepts_int_str_decimal() -> None:
    assert Money(amount=10).amount == Decimal("10.00")
    assert Money(amount="10.5").amount == Decimal("10.50")
    assert Money(amount=Decimal("10.555")).amount == Decimal("10.56")


def test_financial_summary_validators() -> None:
    summary = FinancialSummary(
        currency="INR",
        period_start="2026-07",
        period_end="2026-09",
        months_covered=3,
        monthly_income=Money(amount=Decimal("85000.00")),
        monthly_expenses=Money(amount=Decimal("50000.00")),
        available_surplus=SignedMoney(amount=Decimal("35000.00")),
        category_totals={
            ExpenseCategory.housing: Money(amount=Decimal("25000.00")),
            ExpenseCategory.groceries: Money(amount=Decimal("25000.00")),
        },
    )
    assert summary.monthly_expenses.amount == Decimal("50000.00")

    with pytest.raises(ValidationError):
        FinancialSummary(
            currency="INR",
            period_start="2026-07",
            period_end="2026-09",
            months_covered=3,
            monthly_income=Money(amount=Decimal("85000.00")),
            monthly_expenses=Money(amount=Decimal("50000.00")),
            available_surplus=SignedMoney(amount=Decimal("35000.00")),
            category_totals={
                ExpenseCategory.housing: Money(amount=Decimal("25000.00")),
            },
        )


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1.00"), extra_field=True)  # type: ignore[call-arg]


def test_compute_version_deterministic_and_sensitive() -> None:
    payload = {"a": 1, "b": Decimal("2.50")}
    v1 = compute_version("test", payload)
    v2 = compute_version("test", payload)
    assert v1 == v2
    assert v1.startswith("test-")
    assert len(v1.split("-", 1)[1]) == 12

    changed = compute_version("test", {"a": 1, "b": Decimal("2.51")})
    assert changed != v1


def _json_roundtrip(model: object) -> None:
    assert hasattr(model, "model_dump")
    data = model.model_dump(mode="json")
    type(model).model_validate(data)


def test_json_roundtrip_top_level_models() -> None:
    profile = sample_profile()
    _json_roundtrip(profile)

    savings = SavingsGoal(monthly_target=Money(amount=Decimal("15000.00")))
    _json_roundtrip(savings)

    summary = FinancialSummary(
        currency="INR",
        period_start="2026-07",
        period_end="2026-09",
        months_covered=3,
        monthly_income=Money(amount=Decimal("85000.00")),
        monthly_expenses=Money(amount=Decimal("50000.00")),
        available_surplus=SignedMoney(amount=Decimal("35000.00")),
        category_totals={
            ExpenseCategory.housing: Money(amount=Decimal("25000.00")),
            ExpenseCategory.groceries: Money(amount=Decimal("25000.00")),
        },
    )
    _json_roundtrip(summary)

    _json_roundtrip(ExpenseAnalysisRequest(profile=profile))

    analysis = ExpenseAnalysisResult(
        agent=AgentName.expense_analysis,
        status=AgentStatus.success,
        analysis_version="ea-deadbeeff00d",
        summary=summary,
    )
    _json_roundtrip(analysis)

    _json_roundtrip(BudgetRequest(expense_analysis=analysis, savings_goal=savings))

    feasibility = Feasibility(
        is_feasible=True,
        requested_monthly_savings=Money(amount=Decimal("15000.00")),
        max_achievable_monthly_savings=Money(amount=Decimal("39902.00")),
        shortfall=Money(amount=Decimal("0.00")),
        suggestions=["Reduce dining and one-off shopping."],
    )
    budget = BudgetPlan(
        agent=AgentName.budget_planning,
        status=AgentStatus.success,
        currency="INR",
        monthly_income=Money(amount=Decimal("85000.00")),
        category_limits=[
            CategoryBudget(
                category=ExpenseCategory.housing,
                monthly_limit=Money(amount=Decimal("25000.00")),
                current_monthly_spend=Money(amount=Decimal("25000.00")),
                is_essential=True,
                rationale="Fixed rent",
            ),
            CategoryBudget(
                category=ExpenseCategory.groceries,
                monthly_limit=Money(amount=Decimal("45000.00")),
                current_monthly_spend=Money(amount=Decimal("8300.00")),
                is_essential=False,
                rationale="Flexible",
            ),
        ],
        planned_monthly_savings=Money(amount=Decimal("15000.00")),
        feasibility=feasibility,
    )
    _json_roundtrip(budget)

    _json_roundtrip(ResearchRequest(question="What is SIP?"))

    source = SourceMetadata(
        source_id="S1",
        title="RBI FAQ",
        url="https://rbi.org.in/",
        publisher="RBI",
        published_date=date(2024, 1, 1),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        tier=SourceTier.official,
    )
    research = ResearchResult(
        agent=AgentName.financial_research,
        status=AgentStatus.success,
        question="What is SIP?",
        findings=[
            ResearchFinding(statement="SIP is periodic investment.", source_ids=["S1"], confidence="high")
        ],
        sources=[source],
        search_provider="tavily",
    )
    _json_roundtrip(research)

    _json_roundtrip(
        ReportRequest(
            expense_analysis=analysis,
            budget=budget,
            research=research,
        )
    )

    report = FinancialReport(
        agent=AgentName.financial_report,
        status=AgentStatus.success,
        validation_status=ValidationStatus.valid,
        validation_summary="OK",
        source_versions=ReportSourceVersions(
            analysis_version="ea-1",
            budget_id="b-1",
            budget_revision=1,
        ),
        sections=ReportSections(
            summary="Overview",
            budget_overview=budget.category_limits,
            research_findings=research.findings,
            sources=research.sources,
        ),
    )
    _json_roundtrip(report)

    _json_roundtrip(
        Transaction(
            id="t1",
            date=date(2026, 7, 1),
            description="Test",
            amount=Money(amount=Decimal("1.00")),
            type="expense",
            category=ExpenseCategory.other,
        )
    )


def test_research_finding_unknown_source_rejected() -> None:
    with pytest.raises(ValidationError):
        ResearchResult(
            agent=AgentName.financial_research,
            status=AgentStatus.success,
            question="Q",
            findings=[ResearchFinding(statement="X", source_ids=["S9"], confidence="low")],
            sources=[],
        )


def test_budget_plan_exceeds_income_rejected() -> None:
    with pytest.raises(ValidationError):
        BudgetPlan(
            agent=AgentName.budget_planning,
            status=AgentStatus.success,
            currency="INR",
            monthly_income=Money(amount=Decimal("10000.00")),
            category_limits=[
                CategoryBudget(
                    category=ExpenseCategory.housing,
                    monthly_limit=Money(amount=Decimal("9000.00")),
                    current_monthly_spend=Money(amount=Decimal("9000.00")),
                    is_essential=True,
                    rationale="",
                ),
            ],
            planned_monthly_savings=Money(amount=Decimal("5000.00")),
            feasibility=Feasibility(
                is_feasible=False,
                requested_monthly_savings=Money(amount=Decimal("5000.00")),
                max_achievable_monthly_savings=Money(amount=Decimal("1000.00")),
                shortfall=Money(amount=Decimal("4000.00")),
            ),
        )
