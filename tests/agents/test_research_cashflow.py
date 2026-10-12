"""Saved-data answers must survive complete search/model unavailability."""
import asyncio
from decimal import Decimal
import pytest

from backend.app.config.settings import Settings
from backend.app.services.adapters.financial_research import FinancialResearchAdapter
from finagent.agents.financial_research.cashflow import cashflow_result
from finagent.agents.financial_research.graph import run_financial_research
from finagent.schemas.financial import FinancialSummary
from finagent.schemas.research import ResearchRequest


def request(expenses="55000.00", language="English", **updates):
    summary = FinancialSummary(currency="INR", period_start="2026-09", period_end="2026-10", months_covered=2,
        monthly_income={"amount":"80000.00"}, monthly_expenses={"amount":expenses},
        available_surplus={"amount":str(Decimal("80000.00")-Decimal(expenses))}, category_totals={"housing":{"amount":expenses}})
    return ResearchRequest(question="Based on my spending, how much could I save each month?",
        response_language=language, financial_context={"summary":summary, "is_sample":True}, **updates)


@pytest.mark.parametrize("language, expected", [("English","25,000.00 INR"), ("Bengali","সঞ্চয়ের"), ("Hindi","बचत")])
def test_savings_answer_never_calls_unavailable_providers(language, expected):
    class Unavailable:
        def __getattr__(self, name):
            raise AssertionError(f"Provider must not be used: {name}")
    result = run_financial_research(request(language=language), llm=Unavailable(), search_provider=Unavailable())
    assert result.status.value == "success"
    assert expected in result.calculated_answer
    assert "25,000.00 INR" in result.calculated_answer
    assert not result.findings and not result.sources and not result.limitations
    assert result.financial_context.is_sample


@pytest.mark.parametrize("expenses, expected", [("90000.00","10,000.00 INR more"), ("80000.00","leaving no recorded surplus")])
def test_deficit_or_zero_does_not_claim_positive_savings(expenses, expected):
    result = cashflow_result(request(expenses))
    assert expected in result.calculated_answer
    assert "could be available for saving" not in result.calculated_answer


def test_missing_context_and_unrelated_or_hypothetical_questions_use_research():
    assert cashflow_result(ResearchRequest(question="How much can I save?")) is None
    for question in ["How do emergency funds work?", "How much can I save if I double my income?", "Which stock should I buy?"]:
        assert cashflow_result(request().model_copy(update={"question":question})) is None


def test_adapter_answers_without_even_configured_keys():
    adapter = FinancialResearchAdapter(Settings(_env_file=None, LLM_PROVIDER=None, LLM_MODEL=None, TAVILY_API_KEY=None))
    result = asyncio.run(adapter.run(request(language="Bengali").model_dump(mode="json")))
    assert result.status == "success"
    assert "সঞ্চয়ের" in result.result["calculated_answer"]
    assert result.provenance.input_hash


def test_brief_and_detailed_preserve_caveats_and_demo_label():
    brief = cashflow_result(request(response_detail="brief")).calculated_answer
    detailed = cashflow_result(request(response_detail="detailed")).calculated_answer
    assert len(detailed) > len(brief)
    assert "not your current bank balance" in brief
    assert "DEMO" in brief
