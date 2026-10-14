"""Adapter for evidence-backed financial research."""

from __future__ import annotations

from typing import Any

from finagent.agents.financial_research.graph import run_financial_research
from finagent.agents.financial_research.cashflow import cashflow_result
from finagent.agents.financial_research.search import (
    ConfigurationError,
    SearchProvider,
    get_search_provider,
)
from finagent.config import Settings as FinAgentSettings
from finagent.schemas.common import AgentError, AgentStatus
from finagent.schemas.research import ResearchRequest, ResearchResult
from pydantic import ValidationError

from backend.app.schemas.common import AdapterStatus, AgentEnvelope
from backend.app.services.adapters.base import (
    AgentAdapterBase,
    Context,
    begin_timing,
)


class FinancialResearchAdapter(AgentAdapterBase):
    name = "financial_research"
    capabilities_list = ("financial_education_research", "source_citation")

    def status(self) -> AdapterStatus:
        missing: list[str] = []
        if self.settings.search_provider.strip().lower() != "tavily":
            missing.append("SEARCH_PROVIDER (supported: tavily)")
        elif not (self.settings.tavily_api_key or "").strip():
            missing.append("TAVILY_API_KEY")
        if missing:
            return AdapterStatus(status="misconfigured", missing=missing)
        llm_missing = self.missing_llm_configuration()
        if llm_missing:
            if self.settings.llm_provider and self.settings.llm_model:
                return AdapterStatus(status="misconfigured", missing=llm_missing)
            return AdapterStatus(status="partial", missing=llm_missing)
        return AdapterStatus(status="available")

    async def run(self, input: Any, context: Context = None) -> AgentEnvelope:
        started_at, started_counter = begin_timing()
        try:
            request = ResearchRequest.model_validate(input)
        except ValidationError as exc:
            return self.validation_failure(
                input_value=input,
                error=exc,
                started_at=started_at,
                started_counter=started_counter,
            )
        calculated = cashflow_result(request)
        if calculated is not None:
            return self.envelope(input_value=input, result=calculated,
                started_at=started_at, started_counter=started_counter)
        try:
            provider = (
                context["search_provider"]
                if context is not None and "search_provider" in context
                else self._configured_search_provider()
            )
        except ConfigurationError as exc:
            result = ResearchResult(
                status=AgentStatus.failed,
                question=request.question,
                errors=[
                    AgentError(
                        code="search_not_configured",
                        message=str(exc),
                    )
                ],
            )
            return self.envelope(
                input_value=input,
                result=result,
                started_at=started_at,
                started_counter=started_counter,
            )
        try:
            llm = self.resolve_llm(context)
        except Exception as exc:
            return self.failed_envelope(
                input_value=input,
                started_at=started_at,
                started_counter=started_counter,
                code="misconfigured",
                message=str(exc),
            )
        envelope = await self.invoke(
            input_value=input,
            operation=lambda: run_financial_research(
                request,
                llm=llm,
                search_provider=provider,
            ),
            started_at=started_at,
            started_counter=started_counter,
        )

        if envelope.result is not None and request.financial_context is not None:
            envelope.result["financial_context"] = request.financial_context.model_dump(mode="json")
        return envelope

    def _configured_search_provider(self) -> SearchProvider:
        settings = FinAgentSettings(
            LLM_PROVIDER=self.settings.llm_provider,
            LLM_MODEL=self.settings.llm_model,
            LLM_TEMPERATURE=self.settings.llm_temperature,
            ANTHROPIC_API_KEY=self.settings.anthropic_api_key,
            OPENAI_API_KEY=self.settings.openai_api_key,
            GOOGLE_API_KEY=self.settings.google_api_key,
            SEARCH_PROVIDER=self.settings.search_provider,
            TAVILY_API_KEY=self.settings.tavily_api_key,
            SEARCH_MAX_RESULTS=self.settings.search_max_results,
            SEARCH_TIMEOUT_SECONDS=self.settings.search_timeout_seconds,
            OFFICIAL_DOMAINS=",".join(self.settings.official_domains),
        )
        return get_search_provider(settings)
