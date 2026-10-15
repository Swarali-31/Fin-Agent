"""Adapter integration tests use synthetic in-memory providers only."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from finagent.schemas.budget import BudgetPlan, BudgetRequest, CategoryBudget, Feasibility
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    SignedMoney,
    SourceTier,
    TransactionType,
)
from finagent.schemas.expense import ExpenseAnalysisRequest, ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, FinancialSummary, SavingsGoal, Transaction
from finagent.schemas.research import ResearchFinding, ResearchRequest, ResearchResult, SourceMetadata
from finagent.schemas.report import ReportRequest

from backend.app.config.settings import Settings
from backend.app.schemas.common import AgentEnvelope
from backend.app.services.adapters import (
    BudgetPlanningAdapter,
    ExpenseAnalysisAdapter,
    FinancialReportAdapter,
    FinancialResearchAdapter,
)


class SyntheticStructuredModel:
    """Small deterministic structured-output fake; it never performs network I/O."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.schema: type | None = None

    def with_structured_output(self, schema: type) -> SyntheticStructuredModel:
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if self.error is not None:
            raise self.error
        schema_name = self.schema.__name__ if self.schema else ""
        if schema_name == "ExpenseInterpretation":
            return {"spending_patterns": [], "clarifying_questions": []}
        if schema_name == "QueryPlan":
            return {
                "search_queries": ["TEST FIXTURE: financial education"],
                "is_personalized_advice_request": False,
            }
        if schema_name == "ResearchSynthesis":
            return {
                "findings": [
                    {
                        "statement": "TEST FIXTURE: diversification is an educational concept.",
                        "source_ids": ["S1"],
                        "confidence": "medium",
                    }
                ],
                "limitations": [],
            }
        if schema_name == "ReportComposition":
            return {
                "summary": "The supplied inputs support a general financial overview.",
                "spending_insights": [],
                "savings_opportunities": [],
                "risk_considerations": [],
            }
        raise AssertionError(f"Unexpected schema: {schema_name}")


class SyntheticSearchProvider:
    """Clearly synthetic search data using reserved example.invalid URLs."""

    name = "synthetic-test-provider"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def search(
        self,
        query: str,
        max_results: int,
        include_domains: list[str] | None = None,
    ) -> list[SyntheticRawSearchResult]:
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        return [
            SyntheticRawSearchResult(
                title="TEST FIXTURE - synthetic regulator education",
                url="https://rbi.example.invalid/test-fixture",
                content="TEST FIXTURE: synthetic public education content.",
            ),
            SyntheticRawSearchResult(
                title="TEST FIXTURE - synthetic investor education",
                url="https://sebi.example.invalid/test-fixture",
                content="TEST FIXTURE: synthetic investor education content.",
            ),
        ]


@dataclass(frozen=True)
class SyntheticRawSearchResult:
    title: str
    url: str
    content: str
    published_date: str | None = None


class TestFixtures:
    """Factories produce explicitly synthetic shared-schema test payloads."""

    @staticmethod
    def profile() -> FinancialProfile:
        return FinancialProfile(
            profile_id="TEST FIXTURE - synthetic profile",
            currency="INR",
            transactions=[
                Transaction(
                    id="TEST-FIXTURE-income",
                    date=date(2026, 10, 1),
                    description="TEST FIXTURE: monthly income",
                    amount=Money(amount="1000.00"),
                    type=TransactionType.income,
                    is_recurring=True,
                ),
                Transaction(
                    id="TEST-FIXTURE-housing",
                    date=date(2026, 10, 2),
                    description="TEST FIXTURE: housing expense",
                    amount=Money(amount="200.00"),
                    type=TransactionType.expense,
                    category=ExpenseCategory.housing,
                    is_recurring=True,
                ),
                Transaction(
                    id="TEST-FIXTURE-grocery",
                    date=date(2026, 10, 3),
                    description="TEST FIXTURE: grocery expense",
                    amount=Money(amount="100.00"),
                    type=TransactionType.expense,
                    category=ExpenseCategory.groceries,
                    is_recurring=False,
                ),
                Transaction(
                    id="TEST-FIXTURE-dining",
                    date=date(2026, 10, 4),
                    description="TEST FIXTURE: dining expense",
                    amount=Money(amount="100.00"),
                    type=TransactionType.expense,
                    category=ExpenseCategory.dining,
                    is_recurring=False,
                ),
            ],
        )

    @staticmethod
    def analysis() -> ExpenseAnalysisResult:
        return ExpenseAnalysisResult(
            status=AgentStatus.success,
            analysis_version="ea-test-fixture",
            summary=FinancialSummary(
                currency="INR",
                period_start="2026-10",
                period_end="2026-10",
                months_covered=1,
                monthly_income=Money(amount="1000.00"),
                monthly_expenses=Money(amount="400.00"),
                available_surplus=SignedMoney(amount="600.00"),
                category_totals={
                    ExpenseCategory.housing: Money(amount="200.00"),
                    ExpenseCategory.groceries: Money(amount="100.00"),
                    ExpenseCategory.dining: Money(amount="100.00"),
                },
            ),
            spending_patterns=[],
            data_gaps=[],
        )

    @staticmethod
    def budget() -> BudgetPlan:
        return BudgetPlan(
            status=AgentStatus.success,
            budget_id="bp-test-fixture",
            source_analysis_version="ea-test-fixture",
            currency="INR",
            monthly_income=Money(amount="1000.00"),
            essential_categories=[
                ExpenseCategory.housing,
                ExpenseCategory.groceries,
            ],
            category_limits=[
                CategoryBudget(
                    category=ExpenseCategory.housing,
                    monthly_limit=Money(amount="200.00"),
                    current_monthly_spend=Money(amount="200.00"),
                    is_essential=True,
                    rationale="TEST FIXTURE: essential category.",
                ),
                CategoryBudget(
                    category=ExpenseCategory.groceries,
                    monthly_limit=Money(amount="100.00"),
                    current_monthly_spend=Money(amount="100.00"),
                    is_essential=True,
                    rationale="TEST FIXTURE: essential category.",
                ),
                CategoryBudget(
                    category=ExpenseCategory.dining,
                    monthly_limit=Money(amount="100.00"),
                    current_monthly_spend=Money(amount="100.00"),
                    is_essential=False,
                    rationale="TEST FIXTURE: discretionary category.",
                ),
            ],
            planned_monthly_savings=Money(amount="600.00"),
            feasibility=Feasibility(
                is_feasible=True,
                requested_monthly_savings=Money(amount="600.00"),
                max_achievable_monthly_savings=Money(amount="660.00"),
                shortfall=Money(amount="0.00"),
            ),
        )

    @staticmethod
    def research() -> ResearchResult:
        source = SourceMetadata(
            source_id="S1",
            title="TEST FIXTURE - synthetic investor education",
            url="https://education.example.invalid/guide",
            publisher="example.invalid",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            tier=SourceTier.other,
            snippet="TEST FIXTURE: synthetic content only.",
        )
        return ResearchResult(
            status=AgentStatus.success,
            question="TEST FIXTURE: educational question",
            findings=[
                ResearchFinding(
                    statement="TEST FIXTURE: diversification is an educational concept.",
                    source_ids=["S1"],
                    confidence="medium",
                )
            ],
            sources=[source],
            search_provider="synthetic-test-provider",
        )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def assert_agent_envelope(envelope: AgentEnvelope, status: str) -> None:
    assert envelope.status == status
    assert envelope.provenance.agent == envelope.agent
    assert len(envelope.provenance.input_hash) == 64
    assert envelope.provenance.duration_ms >= 0


def test_expense_adapter_success_partial_failed_and_misconfigured() -> None:
    adapter = ExpenseAnalysisAdapter(Settings())
    request = ExpenseAnalysisRequest(profile=TestFixtures.profile())

    success = run(adapter.run(request, {"llm": SyntheticStructuredModel()}))
    partial = run(adapter.run(request, {"llm": False}))
    failed = run(adapter.run({"profile": {"profile_id": "missing-transactions"}}))

    assert_agent_envelope(success, "success")
    assert_agent_envelope(partial, "partial")
    assert_agent_envelope(failed, "failed")
    assert failed.errors[0]["code"] == "invalid_input"

    misconfigured = ExpenseAnalysisAdapter(
        Settings(LLM_PROVIDER="openai", LLM_MODEL="synthetic-model")
    )
    assert misconfigured.status().status == "misconfigured"
    assert misconfigured.status().missing == ["OPENAI_API_KEY"]
    bad_run = run(
        misconfigured.run(request)
    )
    assert_agent_envelope(bad_run, "failed")
    assert bad_run.errors[0]["code"] == "misconfigured"


def test_budget_adapter_create_revise_partial_failed_and_misconfigured() -> None:
    adapter = BudgetPlanningAdapter(Settings())
    analysis = TestFixtures.analysis()
    request = BudgetRequest(
        expense_analysis=analysis,
        savings_goal=SavingsGoal(monthly_target=Money(amount="100.00")),
    )

    success = run(adapter.create(request, {"llm": False}))
    partial = run(
        adapter.create(request, {"llm": SyntheticStructuredModel(error=RuntimeError("synthetic model failure"))})
    )
    failed = run(adapter.create({"expense_analysis": {"status": "invalid"}}))
    revised = run(adapter.revise(success.result, analysis, {"llm": False}))

    assert_agent_envelope(success, "success")
    assert_agent_envelope(partial, "partial")
    assert_agent_envelope(failed, "failed")
    assert_agent_envelope(revised, "success")
    assert revised.result is not None
    assert revised.result["limitations"][-1]["code"] == "revision_not_needed"
    assert success.provenance.budget_id == success.result["budget_id"]
    assert success.provenance.source_analysis_version == analysis.analysis_version

    misconfigured = BudgetPlanningAdapter(
        Settings(LLM_PROVIDER="openai", LLM_MODEL="synthetic-model")
    )
    assert misconfigured.status().status == "misconfigured"
    assert misconfigured.status().missing == ["OPENAI_API_KEY"]
    bad_run = run(misconfigured.create(request))
    assert_agent_envelope(bad_run, "failed")
    assert bad_run.errors[0]["code"] == "misconfigured"


def test_research_adapter_success_partial_failed_and_misconfigured() -> None:
    configured = Settings(TAVILY_API_KEY="test-placeholder")
    adapter = FinancialResearchAdapter(configured)
    request = ResearchRequest(question="TEST FIXTURE: general financial education")
    context = {
        "llm": SyntheticStructuredModel(),
        "search_provider": SyntheticSearchProvider(),
    }

    success = run(adapter.run(request, context))
    partial = run(
        adapter.run(
            request,
            {
                "llm": SyntheticStructuredModel(error=RuntimeError("synthetic model failure")),
                "search_provider": SyntheticSearchProvider(),
            },
        )
    )
    failed = run(
        adapter.run(
            request,
            {
                "llm": SyntheticStructuredModel(),
                "search_provider": SyntheticSearchProvider(fail=True),
            },
        )
    )

    assert_agent_envelope(success, "success")
    assert_agent_envelope(partial, "partial")
    assert_agent_envelope(failed, "failed")
    assert success.result is not None
    assert all(
        "example.invalid" in source["url"]
        for source in success.result["sources"]
    )

    misconfigured = FinancialResearchAdapter(Settings(TAVILY_API_KEY=None))
    assert misconfigured.status().status == "misconfigured"
    assert misconfigured.status().missing == ["TAVILY_API_KEY"]
    missing_key = run(misconfigured.run(request))
    assert_agent_envelope(missing_key, "failed")
    assert missing_key.errors[0]["code"] == "search_not_configured"
    assert "TAVILY_API_KEY" in missing_key.errors[0]["message"]


def test_report_adapter_success_partial_failed_and_misconfigured() -> None:
    analysis = TestFixtures.analysis()
    budget = TestFixtures.budget()
    request = ReportRequest(
        expense_analysis=analysis,
        budget=budget,
        research=TestFixtures.research(),
    )
    adapter = FinancialReportAdapter(Settings())

    success = run(adapter.run(request, {"llm": SyntheticStructuredModel()}))
    partial = run(
        adapter.run(
            request.model_copy(update={"research": None}),
            {"llm": False},
        )
    )
    stale_budget = budget.model_copy(
        update={"source_analysis_version": "ea-stale000000"}
    )
    failed = run(
        adapter.run(
            request.model_copy(update={"budget": stale_budget}),
            {"llm": SyntheticStructuredModel()},
        )
    )

    assert_agent_envelope(success, "success")
    assert_agent_envelope(partial, "partial")
    assert_agent_envelope(failed, "failed")
    assert failed.result is not None
    assert failed.result["sections"] is None
    assert success.provenance.report_version == success.result["report_version"]

    misconfigured = FinancialReportAdapter(
        Settings(LLM_PROVIDER="openai", LLM_MODEL="synthetic-model")
    )
    assert misconfigured.status().status == "misconfigured"
    assert misconfigured.status().missing == ["OPENAI_API_KEY"]
    bad_run = run(misconfigured.run(request))
    assert_agent_envelope(bad_run, "failed")
    assert bad_run.errors[0]["code"] == "misconfigured"


def test_agent_envelopes_preserve_full_result_and_decimal_string_values() -> None:
    adapter = BudgetPlanningAdapter(Settings())
    result = run(
        adapter.create(
            BudgetRequest(
                expense_analysis=TestFixtures.analysis(),
                savings_goal=SavingsGoal(monthly_target=Money(amount="100.00")),
            ),
            {"llm": False},
        )
    )

    assert result.result is not None
    assert result.result["feasibility"]["is_feasible"] is True
    assert isinstance(result.result["monthly_income"]["amount"], str)
    assert isinstance(result.result["planned_monthly_savings"]["amount"], str)
    assert all(
        isinstance(category["monthly_limit"]["amount"], str)
        for category in result.result["category_limits"]
    )
    assert result.model_dump(mode="json")["result"] == result.result


def test_budget_run_action_dispatch_and_adapter_protocol() -> None:
    adapter = BudgetPlanningAdapter(Settings())
    analysis = TestFixtures.analysis()
    initial = run(
        adapter.run(
            {
                "action": "create",
                "request": BudgetRequest(
                    expense_analysis=analysis,
                    savings_goal=SavingsGoal(monthly_target=Money(amount="100.00")),
                ),
            },
            {"llm": False},
        )
    )
    revised = run(
        adapter.run(
            {
                "action": "revise",
                "previous": initial.result,
                "new_analysis": analysis,
            },
            {"llm": False},
        )
    )

    assert_agent_envelope(initial, "success")
    assert_agent_envelope(revised, "success")
