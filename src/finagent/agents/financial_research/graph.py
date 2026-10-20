"""LangGraph workflow for evidence-backed financial education."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from finagent.agents.financial_research.prompts import (
    QUERY_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    QueryPlan,
    ResearchSynthesis,
    query_planning_prompt,
    conversational_question,
    synthesis_prompt,
)
from finagent.agents.financial_research.cashflow import cashflow_result
from finagent.agents.financial_research.search import (
    ConfigurationError,
    RawSearchResult,
    SearchProvider,
    get_search_provider,
)
from finagent.agents.financial_research.source_ranking import (
    official_domain_list,
    rank_and_dedupe_sources,
)
from finagent.config import Settings, get_settings
from finagent.schemas.common import (
    AgentError,
    AgentStatus,
    Limitation,
)
from finagent.schemas.research import (
    ResearchFinding,
    ResearchRequest,
    ResearchResult,
    SourceMetadata,
)

_ADVICE_REQUEST_RE = re.compile(
    r"\b(?:which|what)\b.{0,50}\b(?:stock|share|fund|crypto|security)\b.{0,40}\b(?:should\s+i|buy|invest|sell)\b"
    r"|\bshould\s+i\s+(?:buy|sell|invest\s+in)\b",
    re.IGNORECASE,
)
_PRESCRIPTIVE_RE = re.compile(
    r"\b(?:buy|sell|hold)\s+[^.!?\n]{0,70}\b(?:shares?|stocks?|securities|crypto|tokens?)\b"
    r"|\b(?:buy|sell|hold)\s+(?:shares?|stocks?|securities|crypto|tokens?)\b",
    re.IGNORECASE,
)
_NAMED_INVESTMENT_RE = re.compile(
    r"\b(?:[Ii]nvest|[Bb]uy|[Ss]ell|[Hh]old)\s+(?:(?:in|into)\s+)?"
    r"(?:[A-Z]{2,6}\b|[A-Z][A-Za-z0-9.&-]*(?:\s+[A-Z][A-Za-z0-9.&-]*)*\s+(?:shares?|stock|fund)\b)"
)
_DISCLAIMER = (
    "Guidance uses the financial details available; it is not a guarantee of returns. "
    "This research does not recommend buying, selling, or holding any specific security."
)


class _ResearchState(TypedDict, total=False):
    request: Any
    parsed_request: ResearchRequest
    queries: list[str]
    advice_request: bool
    official_domains: list[str]
    results: list[RawSearchResult]
    search_success_count: int
    search_failures: list[str]
    provider_name: str
    search_error: AgentError
    configuration_error: AgentError
    sources: list[SourceMetadata]
    synthesis: ResearchSynthesis
    findings: list[ResearchFinding]
    limitations: list[Limitation]
    result: ResearchResult


def _failed_result(
    request: ResearchRequest | None,
    code: str,
    message: str,
    *,
    provider_name: str | None = None,
    details: dict[str, Any] | None = None,
) -> ResearchResult:
    return ResearchResult(
        status=AgentStatus.failed,
        question=request.question if request is not None else "",
        search_provider=provider_name,
        errors=[AgentError(code=code, message=message, details=details)],
        disclaimer=_DISCLAIMER,
    )


def _is_advice_request(question: str) -> bool:
    return bool(_ADVICE_REQUEST_RE.search(question))


def _provider_id(provider: SearchProvider) -> str:
    if provider.__class__.__name__ == "TavilySearchProvider":
        return "tavily"
    return str(getattr(provider, "name", provider.__class__.__name__))


def _synthesis_failure_message(error: Exception) -> str:
    """Explain provider failures without exposing credentials or request contents."""
    status = str(getattr(error, "status_code", None) or getattr(error, "code", ""))
    if status == "429":
        return "Sources were found, but the AI provider's quota or request limit was reached. Check the provider quota or try again later."
    if status in {"401", "403"}:
        return "Sources were found, but the AI provider denied access. Check the backend model API key and permissions."
    if status == "404":
        return "Sources were found, but the configured AI model is unavailable. Check the backend model setting."
    if status in {"500", "502", "503", "504"}:
        return "Sources were found, but the AI provider is temporarily unavailable. Please retry shortly."
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "Sources were found, but the AI answer timed out. Please retry; a brief answer may finish faster."
    return "Sources were found, but the AI could not produce a valid answer. Please retry; your question does not need to be changed."


def _settings() -> Settings:
    return get_settings()


def _search_queries(
    provider: SearchProvider,
    queries: list[str],
    *,
    max_results: int,
    include_domains: list[str] | None,
) -> tuple[list[RawSearchResult], int, list[str]]:
    results: list[RawSearchResult] = []
    success_count = 0
    failures: list[str] = []
    for query in queries:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                found = provider.search(
                    query,
                    max_results=max_results,
                    include_domains=include_domains,
                )
                results.extend(found)
                success_count += 1
                last_error = None
                break
            except ConfigurationError:
                raise
            except Exception as exc:
                last_error = exc
                if not getattr(exc, "retryable", True):
                    break
                if attempt == 0:
                    continue
        if last_error is not None:
            failures.append(str(last_error) if type(last_error).__name__ == "SearchError" else "Search could not finish. Please try again; no sources were invented.")
            if not getattr(last_error, "retryable", True):
                break
    return results, success_count, failures


def build_research_graph(
    llm: Any | None = None,
    search_provider: SearchProvider | None = None,
) -> Any:
    """Build the financial research graph.

    The search provider is resolved lazily; no API key or network call is needed
    to construct the graph.
    """

    def plan_queries(state: _ResearchState) -> dict[str, Any]:
        try:
            request = ResearchRequest.model_validate(state.get("request"))
        except ValidationError as exc:
            return {
                "result": _failed_result(
                    None,
                    "invalid_request",
                    "The research request did not match the shared schema.",
                    details={
                        "validation_errors": [
                            {
                                "location": ".".join(str(part) for part in item["loc"]),
                                "message": item["msg"],
                            }
                            for item in exc.errors()
                        ]
                    },
                )
            }

        calculated = cashflow_result(request)
        if calculated is not None:
            return {"result": calculated}
        advice_request = _is_advice_request(request.question)
        try:
            model = llm
            if model is None:
                from finagent.llm import get_llm

                model = get_llm()
            structured_model = model.with_structured_output(QueryPlan)
            response = structured_model.invoke(
                [
                    SystemMessage(content=QUERY_SYSTEM_PROMPT),
                    HumanMessage(
                        content=query_planning_prompt(conversational_question(request), request.jurisdiction)
                    ),
                ]
            )
            plan = QueryPlan.model_validate(response)
            queries = [query.strip() for query in plan.search_queries if query.strip()]
            if not queries:
                raise ValueError("The query planner returned no usable search queries.")
            advice_request = advice_request or plan.is_personalized_advice_request
        except Exception:
            queries = [request.question]

        if advice_request:
            queries = ["General educational factors and risks relevant to: " + request.question]
        return {
            "parsed_request": request,
            "queries": queries[:3],
            "advice_request": advice_request,
        }

    def route_after_planning(state: _ResearchState) -> str:
        return "finish" if state.get("result") is not None else "search_official"

    def search_official(state: _ResearchState) -> dict[str, Any]:
        try:
            settings = _settings()
            domains = official_domain_list(settings.official_domains)
            provider = search_provider or get_search_provider(settings)
        except ConfigurationError as exc:
            return {
                "configuration_error": AgentError(
                    code="search_not_configured",
                    message=str(exc),
                )
            }
        except Exception as exc:
            return {
                "configuration_error": AgentError(
                    code="search_not_configured",
                    message=f"Search configuration is unavailable: {exc}",
                )
            }

        try:
            results, success_count, failures = _search_queries(
                provider,
                state["queries"],
                max_results=state["parsed_request"].max_sources,
                include_domains=domains,
            )
        except ConfigurationError as exc:
            return {
                "configuration_error": AgentError(
                    code="search_not_configured",
                    message=str(exc),
                )
            }
        return {
            "official_domains": domains,
            "results": results,
            "search_success_count": success_count,
            "search_failures": failures,
            "provider_name": _provider_id(provider),
        }

    def route_after_official(state: _ResearchState) -> str:
        if state.get("configuration_error"):
            return "assemble"
        if state.get("search_failures"):
            return "rank_and_dedupe" if state.get("results") else "assemble"
        return "search_general"

    def search_general(state: _ResearchState) -> dict[str, Any]:
        try:
            settings = _settings()
            provider = search_provider or get_search_provider(settings)
            results, success_count, failures = _search_queries(
                provider,
                state["queries"],
                max_results=state["parsed_request"].max_sources,
                include_domains=None,
            )
        except ConfigurationError as exc:
            return {
                "configuration_error": AgentError(
                    code="search_not_configured",
                    message=str(exc),
                )
            }
        except Exception as exc:
            return {
                "search_failures": [f"General search configuration failed: {exc}"]
            }
        return {
            "results": state.get("results", []) + results,
            "search_success_count": state.get("search_success_count", 0) + success_count,
            "search_failures": failures,
        }

    def route_after_general(state: _ResearchState) -> str:
        if state.get("configuration_error") or (state.get("search_failures") and not state.get("results")):
            return "assemble"
        return "rank_and_dedupe"

    def rank_and_dedupe(state: _ResearchState) -> dict[str, Any]:
        sources = rank_and_dedupe_sources(
            state.get("results", []),
            official_domains=state.get("official_domains", []),
            max_sources=state["parsed_request"].max_sources,
        )
        return {"sources": sources}

    def route_after_ranking(state: _ResearchState) -> str:
        return "synthesize" if state.get("sources") else "assemble"

    def synthesize(state: _ResearchState) -> dict[str, Any]:
        request = state["parsed_request"]
        try:
            model = llm
            if model is None:
                from finagent.llm import get_llm

                model = get_llm()
            structured_model = model.with_structured_output(ResearchSynthesis)
            response = structured_model.invoke(
                [
                    SystemMessage(content=SYNTHESIS_SYSTEM_PROMPT),
                    HumanMessage(
                        content=synthesis_prompt(
                            conversational_question(request),
                            [
                                {
                                    "source_id": source.source_id,
                                    "title": source.title,
                                    "url": str(source.url),
                                    "tier": source.tier.value,
                                    "snippet": source.snippet or "",
                                }
                                for source in state["sources"]
                            ],
                            request.financial_context.model_dump(mode="json") if request.financial_context else None,
                            response_detail=request.response_detail,
                        )
                    ),
                ]
            )
            return {"synthesis": ResearchSynthesis.model_validate(response)}
        except Exception as exc:
            return {
                "limitations": state.get("limitations", [])
                + [
                    Limitation(
                        code="synthesis_unavailable",
                        message=_synthesis_failure_message(exc),
                    )
                ]
            }

    def verify(state: _ResearchState) -> dict[str, Any]:
        synthesis = state.get("synthesis")
        if synthesis is None:
            return {}
        known_ids = {source.source_id for source in state.get("sources", [])}
        findings: list[ResearchFinding] = []
        for finding in synthesis.findings:
            if not finding.source_ids or any(source_id not in known_ids for source_id in finding.source_ids):
                continue
            if _PRESCRIPTIVE_RE.search(finding.statement) or _NAMED_INVESTMENT_RE.search(finding.statement):
                continue
            findings.append(
                ResearchFinding(
                    statement=finding.statement,
                    title=finding.title,
                    source_ids=finding.source_ids,
                    confidence=finding.confidence,
                )
            )
        limitations = list(state.get("limitations", []))
        limitations.extend(
            Limitation(code="research_limitation", message=message)
            for message in dict.fromkeys(message.strip() for message in synthesis.limitations)
            if message.strip()
        )
        if state.get("advice_request"):
            limitations.append(
                Limitation(
                    code="personalized_advice_reframed",
                    message=(
                        "The request sought personalized investment advice; results are reframed "
                        "as general education and do not recommend specific securities."
                    ),
                )
            )
        if not findings:
            limitations.append(
                Limitation(
                    code="no_verified_findings",
                    message=(
                        "No findings could be verified against the retrieved sources; "
                        "no unsupported claims are included."
                    ),
                )
            )
        return {"findings": findings, "limitations": limitations}

    def route_after_synthesis(state: _ResearchState) -> str:
        return "assemble" if state.get("result") is not None else "verify"

    def assemble(state: _ResearchState) -> dict[str, Any]:
        request = state.get("parsed_request")
        if request is None:
            return {}
        configuration_error = state.get("configuration_error")
        if configuration_error is not None:
            return {
                "result": ResearchResult(
                    status=AgentStatus.failed,
                    question=request.question,
                    search_provider=state.get("provider_name"),
                    errors=[configuration_error],
                    limitations=(
                        [
                            Limitation(
                                code="personalized_advice_reframed",
                                message=(
                                    "The request sought personalized investment advice; results "
                                    "would be reframed as general education without specific "
                                    "security recommendations."
                                ),
                            )
                        ]
                        if state.get("advice_request")
                        else []
                    ),
                    disclaimer=_DISCLAIMER,
                )
            }

        errors: list[AgentError] = []
        limitations = list(state.get("limitations", []))
        failures = state.get("search_failures", [])
        success_count = state.get("search_success_count", 0)
        if failures:
            errors.append(
                AgentError(
                    code="search_failed",
                    message="One or more search queries failed after one retry.",
                    details={"failures": failures},
                )
            )
            limitations.append(
                Limitation(
                    code="search_incomplete",
                    message="Some searches failed. The answer uses only the sources that were retrieved.",
                )
            )
        sources = state.get("sources", [])
        if not sources and state.get("results"):
            sources = rank_and_dedupe_sources(
                state["results"],
                official_domains=state.get("official_domains", []),
                max_sources=request.max_sources,
            )
        findings = state.get("findings", [])
        if not sources:
            limitations.append(
                Limitation(
                    code="no_sources_found",
                    message="Search returned no usable sources; no findings were generated.",
                )
            )
        elif not findings and not any(item.code in {"no_verified_findings", "synthesis_unavailable"} for item in limitations):
            limitations.append(
                Limitation(
                    code="no_findings",
                    message="No supported answer was found for this question. Try asking something more specific.",
                )
            )
        if state.get("advice_request") and not any(
            item.code == "personalized_advice_reframed" for item in limitations
        ):
            limitations.append(
                Limitation(
                    code="personalized_advice_reframed",
                    message=(
                        "The request sought personalized investment advice; results are reframed "
                        "as general education and do not recommend specific securities."
                    ),
                )
            )
        if failures:
            status = AgentStatus.partial if success_count > 0 else AgentStatus.failed
        elif findings and not limitations:
            status = AgentStatus.success
        else:
            status = AgentStatus.partial
        return {
            "result": ResearchResult(
                status=status,
                question=request.question,
                findings=findings,
                sources=sources,
                search_provider=state.get("provider_name"),
                errors=errors,
                limitations=limitations,
                disclaimer=_DISCLAIMER,
            )
        }

    graph = StateGraph(_ResearchState)
    graph.add_node("plan_queries", plan_queries)
    graph.add_node("search_official", search_official)
    graph.add_node("search_general", search_general)
    graph.add_node("rank_and_dedupe", rank_and_dedupe)
    graph.add_node("synthesize", synthesize)
    graph.add_node("verify", verify)
    graph.add_node("assemble", assemble)
    graph.add_edge(START, "plan_queries")
    graph.add_conditional_edges(
        "plan_queries",
        route_after_planning,
        {"finish": END, "search_official": "search_official"},
    )
    graph.add_conditional_edges(
        "search_official",
        route_after_official,
        {
            "assemble": "assemble",
            "search_general": "search_general",
            "rank_and_dedupe": "rank_and_dedupe",
        },
    )
    graph.add_conditional_edges(
        "search_general",
        route_after_general,
        {"assemble": "assemble", "rank_and_dedupe": "rank_and_dedupe"},
    )
    graph.add_conditional_edges(
        "rank_and_dedupe",
        route_after_ranking,
        {"assemble": "assemble", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", "verify")
    graph.add_edge("verify", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def run_financial_research(
    request: ResearchRequest | dict[str, Any],
    llm: Any | None = None,
    search_provider: SearchProvider | None = None,
) -> ResearchResult:
    """Run financial education research without raising expected failures."""
    try:
        state = build_research_graph(
            llm=llm,
            search_provider=search_provider,
        ).invoke({"request": request})
        result = state.get("result")
        if isinstance(result, ResearchResult):
            return result
        try:
            parsed = ResearchRequest.model_validate(request)
        except ValidationError:
            parsed = None
        return _failed_result(
            parsed,
            "missing_result",
            "Financial research completed without a result.",
        )
    except Exception as exc:
        try:
            parsed = ResearchRequest.model_validate(request)
        except ValidationError:
            parsed = None
        return _failed_result(
            parsed,
            "agent_execution_error",
            f"Financial research could not be completed: {exc}",
        )
