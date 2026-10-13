"""HTTP API tests use SQLite and explicitly synthetic providers/results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from finagent.schemas.budget import BudgetPlan, CategoryBudget, Feasibility
from finagent.schemas.common import (
    AgentStatus,
    ExpenseCategory,
    Money,
    SignedMoney,
    TransactionType,
)
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, FinancialSummary, Transaction
from finagent.schemas.report import FinancialReport
from finagent.schemas.research import ResearchRequest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.config.settings import Settings
from backend.app.db.models import Base
from backend.app.db.session import create_session_factory
from backend.app.main import app
from backend.app.repositories import PersistenceNotConfigured, PostgresRepository
from backend.app.services.adapters import (
    BudgetPlanningAdapter,
    ExpenseAnalysisAdapter,
    FinancialReportAdapter,
    FinancialResearchAdapter,
)
from backend.app.services import api as api_services


class SyntheticStructuredModel:
    """Deterministic LLM test double; all generated content is labelled."""

    def __init__(self) -> None:
        self.schema: type | None = None

    def with_structured_output(self, schema: type) -> SyntheticStructuredModel:
        self.schema = schema
        return self

    def invoke(self, _prompt: Any) -> dict[str, Any]:
        _ = _prompt
        schema_name = self.schema.__name__ if self.schema else ""
        if schema_name == "ExpenseInterpretation":
            return {"spending_patterns": [], "clarifying_questions": []}
        if schema_name == "QueryPlan":
            return {
                "search_queries": ["TEST FIXTURE: general financial education"],
                "is_personalized_advice_request": False,
            }
        if schema_name == "ResearchSynthesis":
            return {
                "findings": [
                    {
                        "statement": "TEST FIXTURE: synthetic general financial education.",
                        "source_ids": ["S1"],
                        "confidence": "low",
                    }
                ],
                "limitations": [],
            }
        if schema_name == "ReportComposition":
            return {
                "summary": "TEST FIXTURE: supplied financial inputs are summarized.",
                "spending_insights": [],
                "savings_opportunities": [],
                "risk_considerations": [],
            }
        raise AssertionError(f"Unexpected structured schema: {schema_name}")


@dataclass(frozen=True)
class SyntheticSearchResult:
    title: str
    url: str
    content: str
    published_date: str | None = None


class SyntheticSearchProvider:
    name = "synthetic-api-test-provider"

    def search(
        self,
        query: str,
        max_results: int,
        include_domains: list[str] | None = None,
    ) -> list[SyntheticSearchResult]:
        _ = query, include_domains
        return [
            SyntheticSearchResult(
                "TEST FIXTURE: synthetic education page",
                "https://example.invalid/education",
                "TEST FIXTURE: synthetic content for API tests.",
            ),
            SyntheticSearchResult(
                "TEST FIXTURE: second synthetic page",
                "https://example.invalid/second",
                "TEST FIXTURE: another synthetic content page.",
            ),
        ][:max_results]


@pytest.fixture
def client() -> Any:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repository = PostgresRepository(create_session_factory(engine))
    app.state.repository = repository
    app.state.adapters = {
        "expense_analysis": ExpenseAnalysisAdapter(Settings(_env_file=None)),
        "budget_planning": BudgetPlanningAdapter(Settings(_env_file=None)),
        "financial_research": FinancialResearchAdapter(
            Settings(_env_file=None, TAVILY_API_KEY="TEST FIXTURE key")
        ),
        "financial_report": FinancialReportAdapter(Settings(_env_file=None)),
    }
    app.state.agent_context = {
        "llm": SyntheticStructuredModel(),
        "search_provider": SyntheticSearchProvider(),
    }
    with TestClient(app) as test_client:
        account = test_client.post("/api/v1/auth/signup", json={"name": "TEST FIXTURE", "email": "api-tests@example.invalid", "password": "test-only-password"})
        assert account.status_code == 201, account.text
        yield test_client, repository.for_user(account.json()["data"]["id"])
    app.state.repository = None
    app.state.adapters = None
    app.state.agent_context = {}
    app.state.workflow_tasks = {}
    Base.metadata.drop_all(engine)
    engine.dispose()


def profile(profile_id: str = "TEST FIXTURE: api-profile") -> FinancialProfile:
    return FinancialProfile(
        profile_id=profile_id,
        currency="INR",
        transactions=[
            Transaction(
                id="TEST-FIXTURE: api-income",
                date=date(2026, 10, 1),
                description="TEST FIXTURE: monthly income",
                amount=Money(amount="1000.00"),
                type=TransactionType.income,
                is_recurring=True,
            ),
            Transaction(
                id="TEST-FIXTURE: api-housing",
                date=date(2026, 10, 2),
                description="TEST FIXTURE: housing cost",
                amount=Money(amount="200.00"),
                type=TransactionType.expense,
                category=ExpenseCategory.housing,
                is_recurring=True,
            ),
        ],
    )


def analysis() -> ExpenseAnalysisResult:
    return ExpenseAnalysisResult(
        status=AgentStatus.success,
        analysis_version="ea-api-fixture",
        summary=FinancialSummary(
            currency="INR",
            period_start="2026-10",
            period_end="2026-10",
            months_covered=1,
            monthly_income=Money(amount="1000.00"),
            monthly_expenses=Money(amount="200.00"),
            available_surplus=SignedMoney(amount="800.00"),
            category_totals={ExpenseCategory.housing: Money(amount="200.00")},
        ),
    )


def budget() -> BudgetPlan:
    return BudgetPlan(
        status=AgentStatus.success,
        budget_id="bp-api-fixture",
        source_analysis_version="ea-api-fixture",
        currency="INR",
        monthly_income=Money(amount="1000.00"),
        essential_categories=[ExpenseCategory.housing],
        category_limits=[
            CategoryBudget(
                category=ExpenseCategory.housing,
                monthly_limit=Money(amount="200.00"),
                current_monthly_spend=Money(amount="200.00"),
                is_essential=True,
                rationale="TEST FIXTURE: housing essential.",
            )
        ],
        planned_monthly_savings=Money(amount="800.00"),
        feasibility=Feasibility(
            is_feasible=True,
            requested_monthly_savings=Money(amount="800.00"),
            max_achievable_monthly_savings=Money(amount="800.00"),
            shortfall=Money(amount="0.00"),
        ),
    )


def assert_envelope(response: Any, status: int = 200) -> dict[str, Any]:
    assert response.status_code == status, response.text
    payload = response.json()
    assert set(payload) == {"request_id", "status", "data", "warnings", "error"}
    assert payload["request_id"]
    return payload


def test_agents_registry_and_cors_header(client: Any) -> None:
    test_client, _ = client
    payload = assert_envelope(test_client.get("/api/v1/agents"))
    assert "expense_analysis" in payload["data"]
    assert "capabilities" in payload["data"]["budget_planning"]

    preflight = test_client.options(
        "/api/v1/agents/expense-analysis/run",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_validation_error_and_not_found_use_envelopes(client: Any) -> None:
    test_client, _ = client
    missing = assert_envelope(
        test_client.post(
            "/api/v1/profiles/missing/transactions",
            json={"transactions": [{"amount": -3}]},
        ),
        404,
    )
    assert missing["error"]["code"] == "profile_not_found"
    sample = profile("TEST FIXTURE: invalid-profile")
    client[1].save_profile(sample)
    client[1].save_transactions(
        sample.profile_id,
        sample.transactions,
        currency=sample.currency,
    )
    invalid = assert_envelope(
        test_client.post(
            f"/api/v1/profiles/{sample.profile_id}/transactions",
            json={"transactions": [{"id": "bad", "amount": -3}]},
        ),
        422,
    )
    assert invalid["error"]["code"] == "transaction_rows_invalid"
    missing_profile = assert_envelope(
        test_client.get("/api/v1/profiles/unknown/summary"),
        404,
    )
    assert missing_profile["error"]["code"] == "profile_not_found"


def test_persistence_not_configured_maps_to_503(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_client, _ = client
    app.state.repository = None

    def missing_repository(*_args: Any, **_kwargs: Any) -> Any:
        _ = _args, _kwargs
        raise PersistenceNotConfigured()

    monkeypatch.setattr(api_services, "get_repository", missing_repository)
    payload = assert_envelope(test_client.get("/api/v1/budgets"), 503)
    assert payload["error"]["code"] == "persistence_not_configured"


def test_expense_analysis_endpoint_calls_real_adapter(client: Any) -> None:
    test_client, _ = client
    payload = assert_envelope(
        test_client.post(
            "/api/v1/agents/expense-analysis/run",
            json={"profile": profile().model_dump(mode="json")},
        )
    )
    assert payload["data"]["agent"] == "expense_analysis"
    assert payload["data"]["result"]["analysis_version"]


def test_budget_create_and_revision_endpoints(client: Any) -> None:
    test_client, _ = client
    request = {
        "expense_analysis": analysis().model_dump(mode="json"),
        "savings_goal": None,
    }
    created = assert_envelope(
        test_client.post("/api/v1/agents/budget-planning/run", json=request)
    )
    plan = created["data"]["result"]
    assert created["data"]["agent"] == "budget_planning"
    assert plan["feasibility"]["is_feasible"] is True

    revised = assert_envelope(
        test_client.post(
            "/api/v1/agents/budget-planning/revise",
            json={
                "previous": plan,
                "new_analysis": analysis().model_dump(mode="json"),
            },
        )
    )
    assert revised["data"]["result"]["revision"] == plan["revision"]


def test_research_and_report_agent_endpoints(client: Any) -> None:
    test_client, _ = client
    research_response = assert_envelope(
        test_client.post(
            "/api/v1/agents/financial-research/run",
            json=ResearchRequest(question="TEST FIXTURE: explain diversification").model_dump(
                mode="json"
            ),
        )
    )
    assert research_response["data"]["agent"] == "financial_research"
    assert all(
        source["url"].startswith("https://example.invalid/")
        for source in research_response["data"]["result"]["sources"]
    )

    report_response = assert_envelope(
        test_client.post(
            "/api/v1/agents/financial-report/run",
            json={
                "expense_analysis": analysis().model_dump(mode="json"),
                "budget": budget().model_dump(mode="json"),
            },
        )
    )
    assert report_response["data"]["agent"] == "financial_report"
    assert report_response["data"]["result"]["report_version"]


def test_transactions_csv_validation_reports_row_errors(client: Any) -> None:
    test_client, repository = client
    sample = profile("TEST FIXTURE: csv-profile")
    repository.save_profile(sample)
    repository.save_transactions(
        sample.profile_id,
        sample.transactions,
        currency=sample.currency,
    )

    response = test_client.post(
        f"/api/v1/profiles/{sample.profile_id}/transactions",
        content=(
            "id,date,description,amount,type\n"
            "TEST-FIXTURE: bad-date,not-a-date,TEST FIXTURE: bad row,10.00,expense\n"
        ),
        headers={"Content-Type": "text/csv"},
    )
    payload = assert_envelope(response, 422)
    assert payload["error"]["code"] == "transaction_rows_invalid"
    assert payload["error"]["details"]["row_errors"][0]["row"] == 1


def test_duplicate_transaction_id_returns_conflict_envelope(client: Any) -> None:
    test_client, repository = client
    saved_profile = profile("TEST FIXTURE: duplicate-profile")
    repository.save_profile(saved_profile)
    repository.save_transactions(
        saved_profile.profile_id,
        saved_profile.transactions,
        currency=saved_profile.currency,
    )

    payload = assert_envelope(
        test_client.post(
            f"/api/v1/profiles/{saved_profile.profile_id}/transactions",
            json={"transactions": [saved_profile.transactions[0].model_dump(mode="json")]},
        ),
        409,
    )
    assert payload["error"]["code"] == "transaction_conflict"


def test_sample_data_is_explicitly_labelled(client: Any) -> None:
    test_client, repository = client
    profile_id = "TEST FIXTURE: sample-profile"
    payload = assert_envelope(
        test_client.post(f"/api/v1/profiles/{profile_id}/sample-data")
    )
    assert payload["data"]["is_sample"] is True
    assert repository.get_profile(profile_id)["is_sample"] is True
    assert all(
        transaction["is_sample"]
        for transaction in repository.get_transactions(profile_id)
    )
    profile = repository.get_profile(profile_id)["profile"]
    analyzed = assert_envelope(
        test_client.post(
            "/api/v1/agents/expense-analysis/run",
            json={"profile": profile},
        )
    )
    assert analyzed["data"]["result"]["analysis_version"]
    assert repository.get_profile(profile_id)["is_sample"] is True
    assert all(
        transaction["is_sample"]
        for transaction in repository.get_transactions(profile_id)
    )


def test_workflow_create_poll_and_trace(client: Any) -> None:
    test_client, _ = client
    created = assert_envelope(
        test_client.post(
            "/api/v1/workflows",
            json={"task": "Research TEST FIXTURE: financial education"},
        ),
        202,
    )
    run_id = created["data"]["run_id"]
    result = None
    for _ in range(50):
        result = test_client.get(f"/api/v1/workflows/{run_id}")
        if result.json()["data"]["status"] != "running":
            break
        import time

        time.sleep(0.02)
    polled = assert_envelope(result)
    assert polled["data"]["status"] in {"success", "partial"}
    workflow_result = polled["data"]["result"]
    assert workflow_result["plan"]["steps"][0]["agent"] == "financial_research"
    assert workflow_result["trace_events"][-1]["type"] == "final"
    assert workflow_result["final_answer"]
    trace = assert_envelope(test_client.get(f"/api/v1/workflows/{run_id}/trace"))
    assert any(event["event_type"] == "final" for event in trace["data"])


def test_list_detail_and_report_download_envelopes(client: Any) -> None:
    test_client, repository = client
    sample = profile("TEST FIXTURE: record-profile")
    repository.save_profile(sample)
    repository.save_report(
        sample.profile_id,
        FinancialReport(
            status=AgentStatus.success,
            report_version="fr-api-fixture",
            validation_status="valid",
            validation_summary="TEST FIXTURE: validated.",
            source_versions={
                "analysis_version": "ea-api-fixture",
                "budget_id": "bp-api-fixture",
                "budget_revision": 1,
            },
            sections={"summary": "TEST FIXTURE: report summary."},
        ),
    )
    report_record = repository.list_reports(limit=1, offset=0)[0][0]
    report_id = report_record["id"]
    missing = assert_envelope(test_client.get("/api/v1/reports/not-present"), 404)
    assert missing["error"]["code"] == "report_not_found"
    downloaded = assert_envelope(
        test_client.get(f"/api/v1/reports/{report_id}/download?format=markdown")
    )
    assert downloaded["data"]["content"].startswith("# Financial report")
    assert "attachment;" in test_client.get(
        f"/api/v1/reports/{report_id}/download?format=markdown"
    ).headers["content-disposition"]
    records = assert_envelope(test_client.get("/api/v1/reports?page=1&page_size=10"))
    assert records["data"]["total"] == 1


def test_stored_profile_workflow_persists_real_specialist_outputs(client: Any) -> None:
    import time
    test_client, repository = client
    # Use native deterministic specialist behavior, not the synthetic planner.
    app.state.agent_context = {"llm": False}
    profile_id = "integration-profile"
    assert_envelope(test_client.post("/api/v1/profiles", json={"profile_id": profile_id}), 201)
    rows = profile(profile_id).model_dump(mode="json")["transactions"]
    rows += [{"id": "income", "date": "2026-01-01", "description": "Salary", "amount": {"amount": "3000.00"}, "type": "income"}]
    assert_envelope(test_client.post(f"/api/v1/profiles/{profile_id}/transactions", json={"transactions": rows}))
    assert len(assert_envelope(test_client.get(f"/api/v1/profiles/{profile_id}/transactions"))["data"]["transactions"]) == len(rows)
    assert any(p["profile_id"] == profile_id for p in assert_envelope(test_client.get("/api/v1/profiles"))["data"])
    created = assert_envelope(test_client.post("/api/v1/workflows", json={"task": "Generate a financial report", "context": {"profile_id": profile_id}}), 202)
    run_id = created["data"]["run_id"]
    for _ in range(100):
        run = test_client.get(f"/api/v1/workflows/{run_id}").json()["data"]
        if run["status"] != "running":
            break
        time.sleep(0.02)
    assert run["status"] in {"success", "partial"}, run
    analysis_record = repository.get_latest_expense_analysis(profile_id)
    budgets, _ = repository.list_budgets(profile_id=profile_id, limit=10, offset=0)
    reports, _ = repository.list_reports(profile_id=profile_id, limit=10, offset=0)
    assert analysis_record and budgets and reports
    assert budgets[0]["result"]["source_analysis_version"] == analysis_record["result"]["analysis_version"]
    changed = {**rows[0], "id": "new-expense"}
    assert_envelope(test_client.post(f"/api/v1/profiles/{profile_id}/transactions", json={"transactions": [changed]}))
    stale = test_client.post(f"/api/v1/agents/budget-planning/run?profile_id={profile_id}", json={})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_analysis"
    assert_envelope(test_client.post("/api/v1/agents/expense-analysis/run", json={"profile_id": profile_id}))
    stale_report = test_client.post(f"/api/v1/agents/financial-report/run?profile_id={profile_id}", json={})
    assert stale_report.status_code == 409
    assert stale_report.json()["error"]["code"] == "stale_budget"
    assert_envelope(test_client.post(f"/api/v1/profiles/{profile_id}/sample-data"), 409)
    assert repository.get_profile(profile_id)["is_sample"] is False


def test_empty_profile_cannot_invent_financial_inputs(client: Any) -> None:
    test_client, _ = client
    assert_envelope(test_client.post("/api/v1/profiles", json={"profile_id": "empty"}), 201)
    response = test_client.post("/api/v1/agents/expense-analysis/run", json={"profile_id": "empty"})
    assert response.status_code == 422


def test_workflow_rejects_profile_changed_during_execution(client: Any) -> None:
    import time
    from threading import Event
    changed_saved = Event()
    test_client, repository = client
    original = profile("changed-during-run")
    repository.save_profile(original)
    repository.save_transactions(original.profile_id, original.transactions, currency=original.currency)
    adapter = app.state.adapters["expense_analysis"]
    run = adapter.run

    async def run_then_change(payload: Any, context: Any) -> Any:
        result = await run(payload, context)
        changed = original.transactions[0].model_copy(update={"amount": Money(amount="999.00")})
        repository.save_transactions(original.profile_id, [changed], currency=original.currency)
        changed_saved.set()
        return result

    adapter.run = run_then_change
    app.state.agent_context = {"llm": False}
    created = assert_envelope(test_client.post("/api/v1/workflows", json={"task": "Analyze my spending", "context": {"profile_id": original.profile_id}}), 202)
    # SQLite StaticPool shares one connection: do not poll while the mutation
    # transaction is open, or a concurrent reader can roll it back.
    assert changed_saved.wait(2)
    for _ in range(100):
        data = test_client.get(f"/api/v1/workflows/{created['data']['run_id']}").json()["data"]
        if data["status"] != "running":
            break
        time.sleep(0.02)
    assert data["status"] == "failed"
    assert data["result"]["errors"][-1]["code"] == "stale_analysis"
    assert repository.get_latest_expense_analysis(original.profile_id) is None


def test_research_with_profile_appears_in_shared_history(client: Any) -> None:
    test_client, repository = client
    repository.save_profile(profile("research-profile"))
    assert_envelope(test_client.post("/api/v1/agents/financial-research/run?profile_id=research-profile", json={"question": "Research financial education"}))
    items, total = repository.list_research_runs(profile_id="research-profile", limit=10, offset=0)
    assert total == 1
    assert items[0]["result"]["sources"]


def test_research_uses_fresh_stored_totals_and_ignores_client_context(client):
    test_client, repository = client
    saved = profile("personal-research")
    repository.save_profile(saved)
    repository.save_transactions(saved.profile_id, saved.transactions, currency=saved.currency)
    response = assert_envelope(test_client.post(
        "/api/v1/agents/financial-research/run?profile_id=personal-research",
        json={"question": "How can I save more?", "financial_context": {"forged": True}},
    ))
    context = response["data"]["result"]["financial_context"]
    assert context["summary"]["monthly_income"]["amount"] == "1000.00"
    assert context["summary"]["monthly_expenses"]["amount"] == "200.00"
    changed = saved.transactions[1].model_copy(update={"amount": Money(amount="350.00")})
    repository.save_transactions(saved.profile_id, [changed], currency=saved.currency)
    response = assert_envelope(test_client.post(
        "/api/v1/agents/financial-research/run?profile_id=personal-research",
        json={"question": "What is my spending now?"},
    ))
    assert response["data"]["result"]["financial_context"]["summary"]["monthly_expenses"]["amount"] == "350.00"
    assert "TEST-FIXTURE: api-housing" not in str(context)


def test_research_missing_profile_rejected_before_model_call(client):
    test_client, _ = client
    response = test_client.post("/api/v1/agents/financial-research/run?profile_id=missing", json={"question": "Help me save"})
    assert response.status_code == 404


def test_research_without_profile_does_not_accept_forged_finances(client):
    test_client, _ = client
    response = assert_envelope(test_client.post("/api/v1/agents/financial-research/run", json={
        "question": "How do emergency funds work?", "financial_context": {"forged": True},
    }))
    assert response["data"]["result"].get("financial_context") is None


def test_personal_research_excludes_stale_budget(client):
    from backend.app.services.research_context import build_research_context
    test_client, repository = client
    saved = profile("research-budget")
    repository.save_profile(saved)
    repository.save_transactions(saved.profile_id, saved.transactions, currency=saved.currency)
    assert_envelope(test_client.post("/api/v1/agents/expense-analysis/run", json={"profile_id": saved.profile_id}))
    assert_envelope(test_client.post("/api/v1/agents/budget-planning/run?profile_id=research-budget", json={}))
    assert build_research_context(repository, saved.profile_id)["budget"] is not None
    changed = saved.transactions[1].model_copy(update={"amount": Money(amount="350.00")})
    repository.save_transactions(saved.profile_id, [changed], currency=saved.currency)
    context = build_research_context(repository, saved.profile_id)
    assert context["budget"] is None
    assert any("stale" in note for note in context["data_notes"])
