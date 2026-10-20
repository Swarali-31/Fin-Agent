from __future__ import annotations

from typing import Any

import pytest

from finagent.agents.financial_research import graph
from finagent.agents.financial_research.graph import run_financial_research
from finagent.agents.financial_research.search import ConfigurationError
from finagent.config import Settings
from finagent.schemas.common import AgentStatus
from finagent.schemas.research import ResearchRequest


@pytest.fixture
def research_request() -> ResearchRequest:
    return ResearchRequest(question="How do SIPs and lump-sum investing differ?")


@pytest.fixture
def settings_with_synthetic_official_domain(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(
        search_provider="tavily",
        tavily_api_key="synthetic-key",
        OFFICIAL_DOMAINS="rbi.example.invalid",
    )
    monkeypatch.setattr(graph, "_settings", lambda: settings)
    return settings


def _synthetic_synthesis(
    *,
    statement: str = "Diversification can help spread exposure across investments.",
    source_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "findings": [
            {
                "statement": statement,
                "source_ids": ["S1"] if source_ids is None else source_ids,
                "confidence": "medium",
            }
        ],
        "limitations": [],
    }


def test_fabricated_source_id_is_dropped_and_urls_are_retrieved_only(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    provider = synthetic_search_provider(results=synthetic_results)
    llm = synthetic_chat_model(
        query_response={
            "search_queries": ["general SIP education"],
            "is_personalized_advice_request": False,
        },
        synthesis_response={
            "findings": [
                {
                    "statement": "Unsupported source claim.",
                    "source_ids": ["S999"],
                    "confidence": "high",
                }
            ],
            "limitations": [],
        },
    )

    result = run_financial_research(
        research_request,
        llm=llm,
        search_provider=provider,
    )

    assert result.status == AgentStatus.partial
    assert result.findings == []
    assert {str(source.url) for source in result.sources}.issubset(
        {item.url for item in synthetic_results}
    )
    assert any(item.code == "no_verified_findings" for item in result.limitations)


def test_missing_source_ids_are_dropped(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    result = run_financial_research(
        research_request,
        llm=synthetic_chat_model(
            query_response={
                "search_queries": ["general SIP education"],
                "is_personalized_advice_request": False,
            },
            synthesis_response=_synthetic_synthesis(source_ids=[]),
        ),
        search_provider=synthetic_search_provider(results=synthetic_results),
    )

    assert not result.findings
    assert any(item.code == "no_verified_findings" for item in result.limitations)


def test_valid_findings_must_use_only_retrieved_source_ids(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    provider = synthetic_search_provider(results=synthetic_results)
    llm = synthetic_chat_model(
        query_response={
            "search_queries": ["general SIP education"],
            "is_personalized_advice_request": False,
        },
        synthesis_response=_synthetic_synthesis(),
    )

    result = run_financial_research(research_request, llm, provider)

    known_ids = {source.source_id for source in result.sources}
    assert result.status == AgentStatus.success
    assert all(set(finding.source_ids) <= known_ids for finding in result.findings)
    assert {str(source.url) for source in result.sources}.issubset(
        {item.url for item in synthetic_results}
    )
    assert "rbi.example.invalid" in provider.calls[0]["include_domains"]


def test_search_failure_retries_and_returns_structured_failure(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
) -> None:
    provider = synthetic_search_provider(fail_count=4, error=RuntimeError("synthetic outage"))
    llm = synthetic_chat_model(
        query_response={
            "search_queries": ["synthetic query one", "synthetic query two"],
            "is_personalized_advice_request": False,
        }
    )

    result = run_financial_research(research_request, llm, provider)

    assert result.status == AgentStatus.failed
    assert result.errors[0].code == "search_failed"
    assert len(provider.calls) == 4
    assert not result.findings


def test_partial_search_failure_answers_from_successfully_retrieved_sources(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    provider = synthetic_search_provider(results=synthetic_results, fail_count=2)
    llm = synthetic_chat_model(
        query_response={
            "search_queries": ["synthetic query one", "synthetic query two"],
            "is_personalized_advice_request": False,
        },
        synthesis_response=_synthetic_synthesis(),
    )

    result = run_financial_research(research_request, llm, provider)

    assert result.status == AgentStatus.partial
    assert result.errors[0].code == "search_failed"
    assert result.sources
    assert result.findings
    assert any(item.code == "search_incomplete" for item in result.limitations)


def test_missing_key_returns_search_not_configured(
    monkeypatch: pytest.MonkeyPatch,
    research_request: ResearchRequest,
    synthetic_chat_model: Any,
) -> None:
    settings = Settings(search_provider="tavily", tavily_api_key=None)
    monkeypatch.setattr(graph, "_settings", lambda: settings)

    result = run_financial_research(research_request, llm=synthetic_chat_model())

    assert result.status == AgentStatus.failed
    assert result.errors[0].code == "search_not_configured"


def test_empty_results_return_limitation_without_findings(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
) -> None:
    result = run_financial_research(
        research_request,
        llm=synthetic_chat_model(
            query_response={
                "search_queries": ["synthetic query"],
                "is_personalized_advice_request": False,
            }
        ),
        search_provider=synthetic_search_provider(),
    )

    assert result.status == AgentStatus.partial
    assert not result.sources
    assert not result.findings
    assert any(item.code == "no_sources_found" for item in result.limitations)


def test_personalized_advice_is_reframed_and_limited(
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    provider = synthetic_search_provider(results=synthetic_results)
    llm = synthetic_chat_model(
        query_response={
            "search_queries": ["buy an identified stock"],
            "is_personalized_advice_request": True,
        },
        synthesis_response=_synthetic_synthesis(),
    )

    result = run_financial_research(
        ResearchRequest(question="Which stock should I buy?"),
        llm,
        provider,
    )

    assert result.status == AgentStatus.partial
    assert any(item.code == "personalized_advice_reframed" for item in result.limitations)
    assert provider.calls[0]["query"].startswith("General educational factors")
    assert not any("buy" in finding.statement.lower() for finding in result.findings)


def test_prescriptive_finding_is_rejected(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    result = run_financial_research(
        research_request,
        llm=synthetic_chat_model(
            query_response={
                "search_queries": ["general education"],
                "is_personalized_advice_request": False,
            },
            synthesis_response=_synthetic_synthesis(
                statement="You should buy Alpha Corp shares."
            ),
        ),
        search_provider=synthetic_search_provider(results=synthetic_results),
    )

    assert result.findings == []
    assert any(item.code == "no_verified_findings" for item in result.limitations)


def test_query_planning_failure_falls_back_to_raw_question(
    research_request: ResearchRequest,
    settings_with_synthetic_official_domain: Settings,
    synthetic_search_provider: Any,
    synthetic_chat_model: Any,
    synthetic_results: list,
) -> None:
    provider = synthetic_search_provider(results=synthetic_results)
    result = run_financial_research(
        research_request,
        llm=synthetic_chat_model(error=RuntimeError("synthetic LLM outage")),
        search_provider=provider,
    )

    assert provider.calls[0]["query"] == research_request.question
    assert result.findings == []
    assert any(item.code in {"synthesis_unavailable", "no_findings"} for item in result.limitations)


def test_configuration_error_is_not_retried(
    research_request: ResearchRequest,
    synthetic_chat_model: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(search_provider="tavily", tavily_api_key=None)
    monkeypatch.setattr(graph, "_settings", lambda: settings)
    monkeypatch.setattr(
        graph,
        "get_search_provider",
        lambda _settings: (_ for _ in ()).throw(ConfigurationError("TAVILY_API_KEY is missing")),
    )

    result = run_financial_research(research_request, llm=synthetic_chat_model())

    assert result.status == AgentStatus.failed
    assert result.errors[0].code == "search_not_configured"


def test_followup_context_is_labelled_as_context_not_evidence():
    from finagent.agents.financial_research.prompts import conversational_question
    request = ResearchRequest(question="Where should I keep it?", conversation=[
        {"role":"user", "content":"What is an emergency fund?"},
        {"role":"assistant", "content":"It is money for unexpected expenses."},
    ])
    prompt = conversational_question(request)
    assert "emergency fund" in prompt
    assert "Current user question: Where should I keep it?" in prompt
    assert "previous answers are not evidence" in prompt


def test_research_language_selection_is_passed_to_grounded_prompt():
    from finagent.agents.financial_research.prompts import conversational_question
    request = ResearchRequest(question="What is a budget?", response_language="Marathi")
    assert "requested language: Marathi" in conversational_question(request)
    assert "source titles and URLs unchanged" in conversational_question(request)
    auto = ResearchRequest(question="बजट क्या है?")
    assert "language of the current user question" in conversational_question(auto)


@pytest.mark.parametrize("detail", ["detailed", "brief"])
def test_answer_depth_reaches_model_and_section_headings_survive(
    detail, settings_with_synthetic_official_domain, synthetic_search_provider,
    synthetic_results, synthetic_chat_model,
):
    model = synthetic_chat_model(
        query_response={"search_queries": ["emergency fund guide"], "is_personalized_advice_request": False},
        synthesis_response={"findings": [{"title": "How to start", "statement": "Save regularly.\n\nReview the goal as your expenses change.", "source_ids": ["S1"], "confidence": "medium"}], "limitations": []},
    )
    prompts = []
    original = model.invoke
    def capture(messages):
        prompts.append(messages)
        return original(messages)
    model.invoke = capture
    result = run_financial_research(ResearchRequest(question="Explain emergency funds", response_detail=detail), llm=model,
        search_provider=synthetic_search_provider(results=synthetic_results))
    assert f"Answer depth: {detail}" in prompts[-1][1].content
    assert result.findings[0].title == "How to start"
    assert "\n\n" in result.findings[0].statement
    assert result.status == AgentStatus.success
    assert result.limitations == []


@pytest.mark.parametrize("statement", [
    "Plan how much you can spend before you buy groceries or household essentials.",
    "Invest in education to develop your financial knowledge before comparing products.",
])
def test_ordinary_explanations_are_not_discarded_as_security_orders(
    statement, settings_with_synthetic_official_domain, synthetic_search_provider,
    synthetic_results, synthetic_chat_model,
):
    result = run_financial_research(ResearchRequest(question="Explain budgeting"), llm=synthetic_chat_model(
        query_response={"search_queries": ["budgeting guide"], "is_personalized_advice_request": False},
        synthesis_response=_synthetic_synthesis(statement=statement),
    ), search_provider=synthetic_search_provider(results=synthetic_results))
    assert result.findings[0].statement == statement
    assert not any(item.code == "no_verified_findings" for item in result.limitations)


@pytest.mark.parametrize("statement", ["You should buy Alpha Corp shares.", "Invest in AAPL today.", "Buy XYZ now."])
def test_named_security_orders_still_rejected(
    statement, settings_with_synthetic_official_domain, synthetic_search_provider,
    synthetic_results, synthetic_chat_model,
):
    result = run_financial_research(ResearchRequest(question="Explain investing risks"), llm=synthetic_chat_model(
        query_response={"search_queries": ["investing risks"], "is_personalized_advice_request": False},
        synthesis_response=_synthetic_synthesis(statement=statement),
    ), search_provider=synthetic_search_provider(results=synthetic_results))
    assert not result.findings
    assert any(item.code == "no_verified_findings" for item in result.limitations)


def test_model_quota_failure_explained_once_without_blame_or_secret_leak(
    settings_with_synthetic_official_domain, synthetic_search_provider,
    synthetic_results, synthetic_chat_model,
):
    class QuotaError(RuntimeError):
        status_code = 429
    result = run_financial_research(ResearchRequest(question="Explain emergency funds"),
        llm=synthetic_chat_model(error=QuotaError("PRIVATE_PROVIDER_ERROR")),
        search_provider=synthetic_search_provider(results=synthetic_results))
    assert result.status == AgentStatus.partial
    assert result.sources
    assert [item.code for item in result.limitations] == ["synthesis_unavailable"]
    assert "quota" in result.limitations[0].message
    assert "PRIVATE_PROVIDER_ERROR" not in result.model_dump_json()


def test_relevant_source_precedes_unrelated_official_result():
    from finagent.agents.financial_research.search import RawSearchResult
    from finagent.agents.financial_research.source_ranking import rank_and_dedupe_sources
    sources=rank_and_dedupe_sources([
        RawSearchResult(title="Unrelated official page",url="https://rbi.org.in/unrelated",content="TEST FIXTURE",score=0.1),
        RawSearchResult(title="Relevant SIP guide",url="https://example.invalid/sip",content="TEST FIXTURE",score=0.95),
    ],official_domains=["rbi.org.in"],max_sources=1)
    assert sources[0].title=="Relevant SIP guide"


def test_personal_budget_guidance_survives_verification_and_context_stays_out_of_search(
    settings_with_synthetic_official_domain, synthetic_search_provider,
    synthetic_results, synthetic_chat_model,
):
    from finagent.agents.financial_research.prompts import conversational_question, synthesis_prompt
    from finagent.schemas.research import ResearchFinancialContext
    request = ResearchRequest(question="How can I build an emergency fund?", financial_context=ResearchFinancialContext(
        data_notes=["PRIVATE_CONTEXT_SENTINEL"],
    ))
    assert "PRIVATE_CONTEXT_SENTINEL" not in conversational_question(request)
    assert "PRIVATE_CONTEXT_SENTINEL" in synthesis_prompt(request.question, [], request.financial_context.model_dump())
    provider = synthetic_search_provider(results=synthetic_results)
    result = run_financial_research(request, llm=synthetic_chat_model(
        query_response={"search_queries": ["emergency fund saving guide"], "is_personalized_advice_request": False},
        synthesis_response=_synthetic_synthesis(statement="You should set aside part of your monthly surplus for emergencies."),
    ), search_provider=provider)
    assert len(result.findings) == 1
    assert not any(item.code == "personalized_advice_reframed" for item in result.limitations)
    assert "PRIVATE_CONTEXT_SENTINEL" not in str(provider.calls)
