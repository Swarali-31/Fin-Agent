"""Search provider contract and Tavily implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from finagent.config import Settings, get_settings


class SearchError(RuntimeError):
    """A configured search provider failed while executing a query."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class ConfigurationError(RuntimeError):
    """Search provider configuration is missing or unsupported."""


@dataclass(frozen=True, slots=True)
class RawSearchResult:
    """Untrusted, provider-returned search result data."""

    title: str
    url: str
    content: str
    published_date: date | str | None = None
    score: float | None = None


@runtime_checkable
class SearchProvider(Protocol):
    """Contract implemented by search providers used in the graph."""

    def search(
        self,
        query: str,
        max_results: int,
        include_domains: list[str] | None = None,
    ) -> list[RawSearchResult]:
        """Return search results matching the query."""


class TavilySearchProvider:
    """Search Tavily using the official ``tavily-python`` client."""

    def __init__(self, api_key: str, timeout_seconds: float) -> None:
        if not api_key.strip():
            raise ConfigurationError("TAVILY_API_KEY is not set.")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from tavily import TavilyClient
            except ImportError as exc:
                raise ConfigurationError(
                    "The Tavily SDK is unavailable; install the project dependencies."
                ) from exc
            self._client = TavilyClient(api_key=self._api_key)
        return self._client

    def search(
        self,
        query: str,
        max_results: int,
        include_domains: list[str] | None = None,
    ) -> list[RawSearchResult]:
        try:
            response = self._get_client().search(
                query=query,
                max_results=max_results,
                include_domains=list(include_domains) if include_domains else None,
                timeout=self._timeout_seconds,
                topic="general",
                search_depth="advanced",
            )
            if not isinstance(response, dict) or not isinstance(response.get("results"), list):
                raise SearchError("The search provider returned an unreadable response. Try again later.")
            results: list[RawSearchResult] = []
            for item in response.get("results", []):
                if not isinstance(item, dict):
                    raise SearchError("The search provider returned an unreadable source.")
                published_date = item.get("published_date")
                if not isinstance(published_date, (str, date)):
                    published_date = None
                results.append(
                    RawSearchResult(
                        title=str(item.get("title") or ""),
                        url=str(item.get("url") or ""),
                        content=str(item.get("content") or ""),
                        published_date=published_date,
                        score=float(item["score"]) if isinstance(item.get("score"), (int, float)) else None,
                    )
                )
            return results
        except (ConfigurationError, SearchError):
            raise
        except Exception as exc:
            status = str(getattr(exc, "status_code", ""))
            message = {"429": "Search request limit reached. Try again later or check your search account quota.", "401": "The search provider rejected the backend API key.", "403": "The search account cannot access this service."}.get(status, "The search provider could not complete this request. Check the connection and try again.")
            if "timeout" in type(exc).__name__.lower():
                message = "The search timed out. Try a shorter question or try again later."
            raise SearchError(message, retryable=status not in {"401", "403", "429"}) from exc


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    """Return the configured provider or raise a clear configuration error."""
    config = settings or get_settings()
    provider_name = config.search_provider.strip().lower()
    if provider_name != "tavily":
        raise ConfigurationError(
            f"Unsupported SEARCH_PROVIDER '{config.search_provider}'. Supported providers: tavily."
        )
    if not config.tavily_api_key or not config.tavily_api_key.strip():
        raise ConfigurationError(
            "TAVILY_API_KEY is not set. Add it to the environment or .env file before running financial research."
        )
    return TavilySearchProvider(
        api_key=config.tavily_api_key.strip(),
        timeout_seconds=config.search_timeout_seconds,
    )
