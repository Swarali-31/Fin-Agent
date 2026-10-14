from __future__ import annotations

import os

import pytest

from finagent.agents.financial_research.search import (
    ConfigurationError,
    RawSearchResult,
    SearchError,
    TavilySearchProvider,
    get_search_provider,
)
from finagent.config import Settings
from finagent.sample_data import sample_research_question


def test_missing_tavily_key_raises_configuration_error() -> None:
    settings = Settings(search_provider="tavily", tavily_api_key=None)

    with pytest.raises(ConfigurationError, match="TAVILY_API_KEY"):
        get_search_provider(settings)


def test_unknown_provider_raises_clear_configuration_error() -> None:
    settings = Settings(search_provider="unsupported", tavily_api_key="synthetic-key")

    with pytest.raises(ConfigurationError, match="Unsupported SEARCH_PROVIDER"):
        get_search_provider(settings)


def test_provider_respects_configured_timeout() -> None:
    provider = TavilySearchProvider(api_key="synthetic-key", timeout_seconds=7.5)
    calls: list[dict[str, object]] = []

    class SyntheticTavilySDKClient:
        """Test-only Tavily SDK double; it never makes a network call."""

        def search(self, **kwargs: object) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "results": [
                    {
                        "title": "Synthetic result",
                        "url": "https://source.example.invalid/article",
                        "content": "Synthetic content.",
                    }
                ]
            }

    provider._client = SyntheticTavilySDKClient()
    results = provider.search(
        "synthetic education query",
        max_results=2,
        include_domains=["example.invalid"],
    )

    assert calls[0]["timeout"] == 7.5
    assert calls[0]["include_domains"] == ["example.invalid"]
    assert results == [
        RawSearchResult(
            title="Synthetic result",
            url="https://source.example.invalid/article",
            content="Synthetic content.",
            published_date=None,
        )
    ]


def test_tavily_sdk_errors_are_wrapped_as_search_error() -> None:
    provider = TavilySearchProvider(api_key="synthetic-key", timeout_seconds=1)

    class SyntheticFailingTavilySDKClient:
        """Test-only SDK double simulating a provider outage."""

        def search(self, **kwargs: object) -> dict[str, object]:
            raise RuntimeError("synthetic Tavily outage")

    provider._client = SyntheticFailingTavilySDKClient()

    with pytest.raises(SearchError, match="synthetic Tavily outage"):
        provider.search("synthetic query", max_results=1)


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("TAVILY_API_KEY"),
    reason="set TAVILY_API_KEY to exercise the live Tavily search API",
)
def test_live_tavily_search_smoke() -> None:
    provider = get_search_provider(
        Settings(
            search_provider="tavily",
            tavily_api_key=os.environ["TAVILY_API_KEY"],
            search_timeout_seconds=15,
        )
    )
    results = provider.search(sample_research_question(), max_results=1)

    assert results
    assert results[0].title
    assert results[0].url.startswith("https://")
