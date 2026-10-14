"""Deterministic source classification, URL deduplication, and ordering."""

from __future__ import annotations

from datetime import UTC, date, datetime
from urllib.parse import urldefrag, urlsplit, urlunsplit

from finagent.agents.financial_research.search import RawSearchResult
from finagent.schemas.common import SourceTier
from finagent.schemas.research import SourceMetadata

DEFAULT_OFFICIAL_DOMAINS = (
    "rbi.org.in",
    "sebi.gov.in",
    "nism.ac.in",
)


def official_domain_list(configured_domains: list[str] | None = None) -> list[str]:
    """Combine configured official domains with the standard India authorities."""
    domains = {
        domain.strip().lower().lstrip(".")
        for domain in (*DEFAULT_OFFICIAL_DOMAINS, *(configured_domains or []))
        if domain.strip()
    }
    return sorted(domains)


def _canonical_url(url: str) -> str:
    without_fragment = urldefrag(url.strip()).url
    parts = urlsplit(without_fragment)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _is_official(url: str, official_domains: list[str]) -> bool:
    try:
        hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in official_domains
    )


def count_credible_results(
    results: list[RawSearchResult],
    official_domains: list[str],
) -> int:
    """Count distinct usable official URLs for the general-search threshold."""
    canonical_urls: set[str] = set()
    for result in results:
        try:
            canonical_url = _canonical_url(result.url)
            parts = urlsplit(canonical_url)
        except ValueError:
            continue
        if (
            parts.scheme in ("http", "https")
            and parts.netloc
            and _is_official(canonical_url, official_domains)
        ):
            canonical_urls.add(canonical_url)
    return len(canonical_urls)


def _published_date(value: date | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def rank_and_dedupe_sources(
    results: list[RawSearchResult],
    *,
    official_domains: list[str],
    max_sources: int,
) -> list[SourceMetadata]:
    """Keep first result per URL and assign stable source IDs with official first."""
    ranked: list[tuple[bool, int, str, str, RawSearchResult]] = []
    seen: set[str] = set()
    domains = [domain.strip().lower().lstrip(".") for domain in official_domains]
    for index, result in enumerate(results):
        try:
            canonical_url = _canonical_url(result.url)
            parts = urlsplit(canonical_url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                continue
        except ValueError:
            continue
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        ranked.append(
            (
                _is_official(canonical_url, domains),
                index,
                canonical_url,
                result.url.strip(),
                result,
            )
        )

    ranked.sort(key=lambda item: (not item[0], item[1], item[2]))
    retrieved_at = datetime.now(UTC)
    sources: list[SourceMetadata] = []
    for index, (is_official, _, _, source_url, result) in enumerate(
        ranked[:max_sources],
        start=1,
    ):
        url = source_url
        publisher = urlsplit(url).hostname
        sources.append(
            SourceMetadata(
                source_id=f"S{index}",
                title=result.title,
                url=url,
                publisher=publisher,
                published_date=_published_date(result.published_date),
                retrieved_at=retrieved_at,
                tier=SourceTier.official if is_official else SourceTier.other,
                snippet=result.content,
            )
        )
    return sources
