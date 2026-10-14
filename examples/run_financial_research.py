"""Run real financial research for the bundled educational question."""

from __future__ import annotations

import json
import sys

from finagent.agents.financial_research.graph import run_financial_research
from finagent.config import Settings, get_settings
from finagent.sample_data import sample_research_question
from finagent.schemas.research import ResearchRequest


def _missing_configuration(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.tavily_api_key or not settings.tavily_api_key.strip():
        missing.append("TAVILY_API_KEY")
    try:
        provider, _ = settings.require_llm_config()
        settings.require_api_key_for_provider(provider)
    except ValueError as exc:
        missing.append(str(exc))
    return missing


def main() -> int:
    settings = get_settings()
    missing = _missing_configuration(settings)
    if missing:
        print(
            "Financial research needs real provider configuration. Set the following "
            "in your environment or .env file:\n"
            "- SEARCH_PROVIDER=tavily\n"
            "- TAVILY_API_KEY=<your Tavily API key>\n"
            "- LLM_PROVIDER=<anthropic, openai, or google>\n"
            "- LLM_MODEL=<model supported by that provider>\n"
            "- The matching provider key (ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY)\n"
            "See .env.example. No synthetic research output was generated.",
            file=sys.stderr,
        )
        return 1

    result = run_financial_research(
        ResearchRequest(question=sample_research_question())
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.status.value != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
