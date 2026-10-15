"""Persistence tests against an isolated in-memory SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from finagent.schemas.budget import BudgetPlan
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    SignedMoney,
    SourceTier,
)
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, FinancialSummary, Transaction
from finagent.schemas.report import (
    FinancialReport,
    ReportSections,
    ReportSourceVersions,
)
from finagent.schemas.research import ResearchResult
from sqlalchemy import create_engine

from backend.app.config.settings import Settings
from backend.app.db.models import Base
from backend.app.db.session import create_session_factory
from backend.app.repositories import (
    PersistenceNotConfigured,
    PostgresRepository,
    get_repository,
)
from backend.app.repositories.postgres import _postgres_repository_for_url


@pytest.fixture
def repository() -> PostgresRepository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield PostgresRepository(create_session_factory(engine))
    Base.metadata.drop_all(engine)
    engine.dispose()


def _profile() -> FinancialProfile:
    return FinancialProfile(
        profile_id="TEST FIXTURE - profile-1",
        currency="INR",
        transactions=[
            Transaction(
                id="TEST-FIXTURE-tx-1",
                date="2026-10-01",
                description="TEST FIXTURE: synthetic groceries",
                amount=Money(amount="123.45"),
                type="expense",
                category=ExpenseCategory.groceries,
                is_recurring=False,
            )
        ],
    )


def _analysis() -> ExpenseAnalysisResult:
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version="ea-test-001",
        summary=FinancialSummary(
            currency="INR",
            period_start="2026-10",
            period_end="2026-10",
            months_covered=1,
            monthly_income=Money(amount="1000.00"),
            monthly_expenses=Money(amount="123.45"),
            available_surplus=SignedMoney(amount="876.55"),
            category_totals={ExpenseCategory.groceries: Money(amount="123.45")},
        ),
    )


def _budget(
    *,
    budget_id: str,
    revision: int,
    source_version: str,
    parent_budget_id: str | None = None,
) -> BudgetPlan:
    return BudgetPlan(
        status=AgentStatus.success,
        budget_id=budget_id,
        revision=revision,
        source_analysis_version=source_version,
        currency="INR",
        monthly_income=Money(amount="1000.00"),
        category_limits=[],
        planned_monthly_savings=Money(amount="1000.00"),
        feasibility={
            "is_feasible": True,
            "requested_monthly_savings": Money(amount="1000.00"),
            "max_achievable_monthly_savings": Money(amount="1000.00"),
            "shortfall": Money(amount="0.00"),
        },
        revision_info=(
            {
                "parent_budget_id": parent_budget_id,
                "previous_source_analysis_version": "ea-test-previous",
                "changes": ["TEST FIXTURE: revision delta"],
            }
            if parent_budget_id
            else None
        ),
    )


def test_database_url_missing_raises_typed_error() -> None:
    with pytest.raises(PersistenceNotConfigured) as captured:
        get_repository(Settings(_env_file=None, DATABASE_URL=None))

    assert captured.value.code == "persistence_not_configured"


def test_configured_postgres_repository_is_lazy_and_uses_psycopg() -> None:
    _postgres_repository_for_url.cache_clear()

    repository = get_repository(
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql://user:password@localhost:5432/finagent",
        )
    )

    assert isinstance(repository, PostgresRepository)
    engine = repository._sessions.kw["bind"]
    assert engine.dialect.driver == "psycopg"
    engine.dispose()
    _postgres_repository_for_url.cache_clear()


def test_profile_and_transactions_keep_exact_numeric_amounts_and_sample_flags(
    repository: PostgresRepository,
) -> None:
    profile = _profile()
    repository.save_profile(profile, is_sample=True)
    count = repository.save_transactions(
        profile.profile_id,
        profile.transactions,
        currency=profile.currency,
        is_sample=True,
    )

    saved_profile = repository.get_profile(profile.profile_id)
    saved_transactions = repository.get_transactions(profile.profile_id)

    assert count == 1
    assert saved_profile is not None
    assert saved_profile["is_sample"] is True
    assert saved_transactions[0]["is_sample"] is True
    assert Decimal(saved_transactions[0]["amount"]) == Decimal("123.45")
    assert saved_transactions[0]["transaction"]["amount"]["amount"] == "123.45"


def test_saves_all_agent_outputs_workflow_and_trace_records(
    repository: PostgresRepository,
) -> None:
    profile = _profile()
    repository.save_profile(profile)
    analysis = _analysis()
    budget = _budget(
        budget_id="bp-test-001",
        revision=1,
        source_version=analysis.analysis_version or "",
    )
    report = FinancialReport(
        status=AgentStatus.success,
        report_version="fr-test-001",
        validation_status="valid",
        validation_summary="Valid: TEST FIXTURE.",
        source_versions=ReportSourceVersions(
            analysis_version=analysis.analysis_version or "",
            budget_id=budget.budget_id or "",
            budget_revision=budget.revision,
        ),
        sections=ReportSections(summary="TEST FIXTURE: report summary."),
    )
    research = ResearchResult(
        status=AgentStatus.partial,
        question="TEST FIXTURE: research prompt",
        sources=[],
        search_provider="TEST FIXTURE",
    )

    analysis_id = repository.save_expense_analysis(profile.profile_id, analysis)
    budget_row_id = repository.save_budget(profile.profile_id, budget)
    research_id = repository.save_research_run(research, profile_id=profile.profile_id)
    report_id = repository.save_report(profile.profile_id, report)
    started = datetime.now(UTC)
    workflow_id = repository.create_workflow_run(
        input_data={"label": "TEST FIXTURE"},
        started_at=started,
        profile_id=profile.profile_id,
    )
    repository.add_trace_event(
        workflow_id,
        event_type="TEST_FIXTURE",
        payload={"is_sample": True},
        agent="test",
    )
    repository.finish_workflow_run(
        workflow_id,
        status="success",
        result_data={"analysis_id": analysis_id, "budget_id": budget.budget_id},
        finished_at=datetime.now(UTC),
    )

    assert analysis_id
    assert budget_row_id
    assert research_id
    assert report_id
    events = repository.list_trace_events(workflow_id)
    assert len(events) == 1
    assert events[0]["payload"] == {"is_sample": True}


def test_budget_lineage_query_returns_parent_and_revisions_in_order(
    repository: PostgresRepository,
) -> None:
    profile = _profile()
    repository.save_profile(profile)
    first = _budget(budget_id="bp-lineage-1", revision=1, source_version="ea-1")
    second = _budget(
        budget_id="bp-lineage-2",
        revision=2,
        source_version="ea-2",
        parent_budget_id="bp-lineage-1",
    )
    third = _budget(
        budget_id="bp-lineage-3",
        revision=3,
        source_version="ea-3",
        parent_budget_id="bp-lineage-2",
    )
    repository.save_budget(profile.profile_id, first)
    repository.save_budget(profile.profile_id, second)
    repository.save_budget(profile.profile_id, third)

    revisions = repository.list_budget_revisions("bp-lineage-2")

    assert [item["budget_id"] for item in revisions] == [
        "bp-lineage-1",
        "bp-lineage-2",
        "bp-lineage-3",
    ]
    assert [item["revision"] for item in revisions] == [1, 2, 3]


def test_transaction_write_requires_saved_profile(repository: PostgresRepository) -> None:
    with pytest.raises(ValueError, match="must be saved"):
        repository.save_transactions(
            "missing-profile",
            _profile().transactions,
            currency="INR",
        )
