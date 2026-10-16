"""Tests for the master-agent workflow using synthetic adapter fixtures."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from backend.app.config.settings import Settings
from backend.app.orchestrator.graph import (
    narrative_is_grounded,
    run_workflow,
)
from backend.app.orchestrator.planning import ProposedPlan, deterministic_plan
from backend.app.schemas.common import AgentEnvelope, AgentProvenance, AdapterStatus


import pytest

@pytest.fixture(autouse=True)
def isolate_workflows_from_live_database(monkeypatch):
    # Synthetic unit runs must never use a developer's configured cloud database.
    monkeypatch.setattr("backend.app.orchestrator.graph.get_repository", lambda **kwargs: None)


def _async_test(function: Any) -> Any:
    def run(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(function(*args, **kwargs))

    return run


class FakeAdapter:
    def __init__(self, name: str, results: list[dict[str, Any]] | None = None):
        self.name = name
        self.results = list(results or [])
        self.calls: list[dict[str, Any]] = []
        self.revisions: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.revision_contexts: list[Any] = []

    def capabilities(self) -> list[str]:
        return [self.name]

    def status(self) -> AdapterStatus:
        return AdapterStatus(status="available")

    async def run(self, input: Any, context: Any = None) -> AgentEnvelope:
        self.calls.append({"input": input, "context": context})
        result = self.results.pop(0) if self.results else result_for(self.name)
        return envelope(self.name, result, result.get("status", "success"))

    async def revise(self, previous: dict[str, Any], new_analysis: dict[str, Any], context: Any = None) -> AgentEnvelope:
        self.revisions.append((previous, new_analysis))
        self.revision_contexts.append(context)
        return envelope(self.name, budget_result(new_analysis["analysis_version"], revision=2))


def envelope(agent: str, result: dict[str, Any], status: str = "success") -> AgentEnvelope:
    return AgentEnvelope(
        agent=agent,
        status=status,
        result=result,
        errors=result.get("errors", []),
        provenance=AgentProvenance(
            agent=agent,
            analysis_version=result.get("analysis_version"),
            budget_id=result.get("budget_id"),
            budget_revision=result.get("revision"),
            source_analysis_version=result.get("source_analysis_version"),
            report_version=result.get("report_version"),
            input_hash="fixture-hash",
            started_at=datetime.now(UTC),
            duration_ms=0,
        ),
    )


def expense_result(version: str = "ea-current") -> dict[str, Any]:
    return {
        "status": "success",
        "analysis_version": version,
        "summary": {
            "monthly_income": {"amount": "1000.00"},
            "monthly_expenses": {"amount": "600.00"},
            "available_surplus": {"amount": "400.00"},
        },
    }


def budget_result(source_version: str = "ea-current", revision: int = 1) -> dict[str, Any]:
    return {
        "status": "success",
        "budget_id": f"bp-{revision}",
        "revision": revision,
        "source_analysis_version": source_version,
        "currency": "INR",
        "monthly_income": {"amount": "1000.00"},
        "category_limits": [],
        "planned_monthly_savings": {"amount": "200.00"},
        "feasibility": {"is_feasible": True, "shortfall": {"amount": "0.00"}},
    }


def report_result(
    analysis_version: str = "ea-current",
    budget_id: str = "bp-1",
    revision: int = 1,
) -> dict[str, Any]:
    return {
        "status": "success",
        "report_version": "fr-current",
        "source_versions": {
            "analysis_version": analysis_version,
            "budget_id": budget_id,
            "budget_revision": revision,
        },
        "validation_status": "valid",
        "validation_summary": "Inputs consistent.",
    }


def result_for(agent: str) -> dict[str, Any]:
    return {
        "expense_analysis": expense_result(),
        "budget_planning": budget_result(),
        "financial_research": {
            "status": "success",
            "question": "TEST FIXTURE: synthetic research question",
            "findings": [],
            "sources": [],
        },
        "financial_report": report_result(),
    }[agent]


def profile_context() -> dict[str, Any]:
    return {
        "profile": {
            "profile_id": "fixture-profile",
            "currency": "INR",
            "transactions": [{"id": "t1", "amount": {"amount": "1000.00"}}],
        }
    }


class StructuredResult:
    def __init__(self, schema: type[BaseModel], response: Any):
        self.schema = schema
        self.response = response
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        return self.response


class FakeLLM:
    def __init__(self, plan: Any, narrative: str | None = None):
        self.plan = plan
        self.narrative = narrative

    def with_structured_output(self, schema: type[BaseModel]) -> StructuredResult:
        if schema is ProposedPlan:
            return StructuredResult(schema, self.plan)
        return StructuredResult(schema, {"summary": self.narrative or "Grounded summary."})


def adapters(*, overrides: dict[str, FakeAdapter] | None = None) -> dict[str, FakeAdapter]:
    values = {
        name: FakeAdapter(name)
        for name in (
            "expense_analysis",
            "budget_planning",
            "financial_research",
            "financial_report",
        )
    }
    values.update(overrides or {})
    return values


@_async_test
async def test_research_task_routes_to_single_independent_agent() -> None:
    registry = adapters()
    result = await run_workflow(
        "Research how compound interest works",
        adapters=registry,
        llm=False,
    )

    assert [step.agent for step in result.plan.steps] == ["financial_research"]
    assert len(registry["financial_research"].calls) == 1
    assert result.status == "success", result.errors


@_async_test
async def test_report_task_routes_to_ordered_multi_agent_pipeline() -> None:
    registry = adapters()
    result = await run_workflow(
        "Prepare a financial report",
        profile_context(),
        adapters=registry,
        llm=False,
    )

    assert [step.agent for step in result.plan.steps] == [
        "expense_analysis",
        "budget_planning",
        "financial_report",
    ]
    budget_input = registry["budget_planning"].calls[0]["input"]
    report_input = registry["financial_report"].calls[0]["input"]
    assert budget_input["expense_analysis"]["analysis_version"] == "ea-current"
    assert report_input["budget"]["budget_id"] == "bp-1"
    assert [event.type for event in result.trace_events].count("agent_call") == 3


@_async_test
async def test_dependency_order_and_actual_results_pass_downstream() -> None:
    registry = adapters(
        overrides={
            "expense_analysis": FakeAdapter(
                "expense_analysis", [expense_result("ea-new")]
            ),
            "budget_planning": FakeAdapter(
                "budget_planning", [budget_result("ea-new")]
            ),
        }
    )
    result = await run_workflow(
        "Create a budget",
        profile_context(),
        adapters=registry,
        llm=False,
    )

    assert registry["budget_planning"].calls[0]["input"]["expense_analysis"]["analysis_version"] == "ea-new"
    assert result.results["budget_planning"].result["source_analysis_version"] == "ea-new"


@_async_test
async def test_retry_limit_allows_initial_call_plus_configured_retries() -> None:
    registry = adapters(
        overrides={
            "financial_research": FakeAdapter(
                "financial_research",
                [
                    {"status": "failed", "errors": [{"code": "temporary"}]},
                    {"status": "failed", "errors": [{"code": "temporary"}]},
                    result_for("financial_research"),
                ],
            )
        }
    )
    result = await run_workflow(
        "Research market volatility",
        adapters=registry,
        llm=False,
        settings=Settings(MAX_RETRIES_PER_STEP=2, RETRY_BACKOFF_SECONDS=0),
    )

    assert len(registry["financial_research"].calls) == 3
    assert result.results["financial_research"].status == "success"
    assert [event.type for event in result.trace_events].count("retry") == 2


@_async_test
async def test_configuration_failure_is_not_retried() -> None:
    registry = adapters(
        overrides={
            "financial_research": FakeAdapter(
                "financial_research",
                [
                    {
                        "status": "failed",
                        "errors": [{"code": "search_not_configured"}],
                    }
                ],
            )
        }
    )
    result = await run_workflow(
        "Research market volatility",
        adapters=registry,
        llm=False,
        settings=Settings(MAX_RETRIES_PER_STEP=3, RETRY_BACKOFF_SECONDS=0),
    )

    assert len(registry["financial_research"].calls) == 1
    assert result.results["financial_research"].status == "failed"
    assert not any(event.type == "retry" for event in result.trace_events)


@_async_test
async def test_stale_budget_is_revised_against_current_analysis() -> None:
    budget = FakeAdapter("budget_planning", [budget_result("ea-old")])
    registry = adapters(overrides={"budget_planning": budget})
    result = await run_workflow(
        "Create a budget",
        profile_context(),
        adapters=registry,
        llm=False,
        settings=Settings(MAX_REPLANS=1, RETRY_BACKOFF_SECONDS=0),
    )

    assert len(budget.calls) == 1
    assert len(budget.revisions) == 1
    assert budget.revisions[0][1]["analysis_version"] == "ea-current"
    assert result.replan_count == 1
    assert result.results["budget_planning"].result["source_analysis_version"] == "ea-current"
    assert any(event.type == "replan" for event in result.trace_events)


@_async_test
async def test_failed_upstream_skips_dependents_but_continues_independent_research() -> None:
    expense = FakeAdapter(
        "expense_analysis",
        [{"status": "failed", "errors": [{"code": "calculation_error"}]}],
    )
    registry = adapters(overrides={"expense_analysis": expense})
    result = await run_workflow(
        "Prepare a financial report with research",
        profile_context(),
        adapters=registry,
        llm=False,
        settings=Settings(MAX_RETRIES_PER_STEP=0),
    )

    assert result.results["financial_research"].status == "success"
    assert result.plan is not None
    assert next(step for step in result.plan.steps if step.agent == "budget_planning").status == "skipped_dependency_failed"
    assert next(step for step in result.plan.steps if step.agent == "financial_report").status == "skipped_dependency_failed"


@_async_test
async def test_invalid_llm_plan_is_rejected_without_fallback() -> None:
    registry = adapters()
    invalid = {"steps": [{"id": "bad", "agent": "untrusted_agent"}]}
    result = await run_workflow(
        "Research market volatility",
        adapters=registry,
        llm=FakeLLM(invalid),
    )

    assert result.status == "failed"
    assert result.errors[0].code == "invalid_plan"
    assert not registry["financial_research"].calls
    assert result.plan is None


@_async_test
async def test_deterministic_fallback_is_labelled_in_trace() -> None:
    result = await run_workflow(
        "Research market volatility",
        adapters=adapters(),
        llm=False,
    )

    plan_event = next(event for event in result.trace_events if event.type == "plan")
    assert plan_event.details["planner"] == "deterministic_fallback"


def test_natural_spending_task_routes_to_analysis_budget_and_independent_research() -> None:
    plan = deterministic_plan(
        "Analyze my spending, build a budget to save 15000/month, and research SIP vs lump-sum",
        {
            "profile": {
                "profile_id": "TEST FIXTURE: profile",
                "currency": "INR",
                "transactions": [{"id": "TEST FIXTURE: transaction"}],
            }
        },
    )

    steps = {step.agent: step for step in plan.steps}
    assert set(steps) == {"expense_analysis", "budget_planning", "financial_research"}
    assert steps["budget_planning"].depends_on == ["expense_analysis"]
    assert steps["financial_research"].depends_on == []


def test_synthesis_rejects_numbers_and_urls_not_in_outputs() -> None:
    results = {
        "financial_research": envelope(
            "financial_research",
            {
                "status": "success",
                "findings": [{"statement": "Synthetic education", "source_ids": ["S1"]}],
                "sources": [{"url": "https://example.invalid/source"}],
            },
        )
    }

    assert narrative_is_grounded(
        "See https://example.invalid/source for the source.", results
    )
    assert not narrative_is_grounded("The return is 98.5%.", results)
    assert not narrative_is_grounded("See https://invented.invalid/path.", results)


@_async_test
async def test_llm_invented_number_and_url_are_replaced_with_deterministic_summary() -> None:
    research_result = {
        "status": "success",
        "question": "Explain a synthetic topic",
        "findings": [
            {
                "statement": "TEST FIXTURE: synthetic educational finding",
                "source_ids": ["S1"],
                "confidence": "low",
            }
        ],
        "sources": [
            {
                "source_id": "S1",
                "title": "TEST FIXTURE: synthetic source",
                "url": "https://example.invalid/source",
            }
        ],
    }
    registry = adapters(
        overrides={
            "financial_research": FakeAdapter(
                "financial_research",
                [research_result],
            )
        }
    )
    plan = {
        "steps": [
            {
                "id": "research",
                "agent": "financial_research",
                "input_refs": {"question": "task"},
            }
        ]
    }
    result = await run_workflow(
        "Research a synthetic topic",
        adapters=registry,
        llm=FakeLLM(
            plan,
            "The result is 98.5%; see https://invented.invalid/page.",
        ),
    )

    assert "deterministic fallback; ungrounded narrative rejected" in result.final_answer
    assert "98.5" not in result.final_answer
    assert result.sources[0]["url"] == "https://example.invalid/source"
    assert any(event.type == "validation" for event in result.trace_events)


@_async_test
async def test_max_steps_guard_stops_before_adapter_calls() -> None:
    registry = adapters()
    result = await run_workflow(
        "Prepare a financial report",
        profile_context(),
        adapters=registry,
        llm=False,
        settings=Settings(MAX_STEPS=2),
    )

    assert result.errors[0].code == "max_steps_exceeded"
    assert all(not adapter.calls for adapter in registry.values())


@_async_test
async def test_max_replans_guard_terminates_on_stale_budget() -> None:
    budget = FakeAdapter("budget_planning", [budget_result("ea-old")])
    result = await run_workflow(
        "Create a budget",
        profile_context(),
        adapters=adapters(overrides={"budget_planning": budget}),
        llm=False,
        settings=Settings(MAX_REPLANS=0, RETRY_BACKOFF_SECONDS=0),
    )

    assert result.replan_count == 1
    assert result.errors[-1].code == "max_replans_exceeded"
    assert not budget.revisions


@_async_test
async def test_missing_profile_returns_structured_error() -> None:
    result = await run_workflow(
        "Create a budget",
        adapters=adapters(),
        llm=False,
    )

    assert result.errors[0].code == "missing_input"
    assert result.status == "failed"
    assert not result.results


@_async_test
async def test_budget_reuses_only_current_saved_analysis():
    from finagent.sample_data import sample_profile
    from finagent.agents.expense_analysis.calculations import compute_expense_metrics
    from finagent.schemas.expense import ExpenseAnalysisResult
    profile=sample_profile()
    metrics=compute_expense_metrics(profile)
    saved=ExpenseAnalysisResult(status='success',analysis_version=metrics.analysis_version,summary=metrics.summary).model_dump(mode='json')
    expense=FakeAdapter('expense_analysis',[saved])
    budget=FakeAdapter('budget_planning',[budget_result(metrics.analysis_version)])
    result=await run_workflow('Create a monthly budget',{'profile':profile.model_dump(mode='json'),'cached_expense_analysis':saved},adapters=adapters(overrides={'expense_analysis':expense,'budget_planning':budget}),llm=False)
    assert expense.calls==[]
    assert budget.calls[0]['input']['expense_analysis']['analysis_version']==metrics.analysis_version
    stale={**saved,'analysis_version':'ea-stale-saved'}
    expense=FakeAdapter('expense_analysis',[saved])
    await run_workflow('Create a monthly budget',{'profile':profile.model_dump(mode='json'),'cached_expense_analysis':stale},adapters=adapters(overrides={'expense_analysis':expense,'budget_planning':FakeAdapter('budget_planning',[budget_result(metrics.analysis_version)])}),llm=False)
    assert len(expense.calls)==1


def test_planner_prompt_names_exact_specialist_input_contracts():
    from backend.app.orchestrator.planning import plan_prompt
    import json
    prompt = json.loads(plan_prompt("Generate a report", {"profile": {"profile_id":"TEST", "transactions":[]}}))
    contract = prompt["input_reference_contract"]
    assert contract["expense_analysis"] == {"profile":"context.profile"}
    assert "expense_analysis" in contract["budget_planning"]
    assert contract["financial_research"] == {"question":"task"}
    assert {"expense_analysis","budget","research"} == set(contract["financial_report"])
