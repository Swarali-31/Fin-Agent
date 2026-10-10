"""Clearly synthetic provider fixtures shared by financial research tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from finagent.agents.financial_research.search import RawSearchResult


class SyntheticSearchProvider:
    """Test-only provider returning obviously synthetic example.invalid URLs."""

    name = "synthetic-test-provider"

    def __init__(
        self,
        results: list[RawSearchResult] | None = None,
        *,
        error: Exception | None = None,
        fail_count: int = 0,
    ) -> None:
        self.results = results or []
        self.error = error
        self.fail_count = fail_count
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        max_results: int,
        include_domains: list[str] | None = None,
    ) -> list[RawSearchResult]:
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "include_domains": include_domains,
            }
        )
        if self.fail_count:
            self.fail_count -= 1
            raise self.error or RuntimeError("synthetic provider failure")
        return list(self.results)


class SyntheticChatModel:
    """Test-only structured model; responses contain synthetic source evidence."""

    def __init__(
        self,
        *,
        query_response: Any | None = None,
        synthesis_response: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        self.query_response = query_response
        self.synthesis_response = synthesis_response
        self.error = error

    def with_structured_output(self, schema: type) -> SyntheticChatModel:
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if self.error is not None:
            raise self.error
        name = self.schema.__name__
        if name == "QueryPlan":
            return self.query_response
        if name == "ResearchSynthesis":
            return self.synthesis_response
        raise AssertionError(f"Unexpected structured output schema: {name}")


@pytest.fixture
def synthetic_search_provider() -> Callable[..., SyntheticSearchProvider]:
    """Factory fixture for in-memory results using reserved .invalid URLs."""
    return SyntheticSearchProvider


@pytest.fixture
def synthetic_chat_model() -> Callable[..., SyntheticChatModel]:
    """Factory fixture for deterministic structured test responses."""
    return SyntheticChatModel


@pytest.fixture
def synthetic_results() -> list[RawSearchResult]:
    """Synthetic official-like and general source result records."""
    return [
        RawSearchResult(
            title="Synthetic regulator explainer",
            url="https://rbi.example.invalid/education/sip",
            content="Synthetic explanation of systematic investment plans.",
            published_date="2025-01-02",
        ),
        RawSearchResult(
            title="Synthetic investor guide",
            url="https://learn.example.invalid/investing/risks",
            content="Synthetic explanation of investment risk and diversification.",
        ),
    ]
