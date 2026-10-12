from __future__ import annotations

from finagent.agents.financial_research.source_ranking import (
    count_credible_results,
    official_domain_list,
    rank_and_dedupe_sources,
)
from finagent.agents.financial_research.search import RawSearchResult


def test_official_sources_rank_first_and_urls_are_deduplicated(
    synthetic_results: list,
) -> None:
    sources = rank_and_dedupe_sources(
        [
            synthetic_results[1],
            synthetic_results[0],
            synthetic_results[0],
        ],
        official_domains=official_domain_list(["rbi.example.invalid"]),
        max_sources=5,
    )

    assert [source.source_id for source in sources] == ["S1", "S2"]
    assert [source.tier.value for source in sources] == ["official", "other"]
    assert len({str(source.url) for source in sources}) == len(sources)


def test_published_date_is_present_only_when_returned(
    synthetic_results: list,
) -> None:
    sources = rank_and_dedupe_sources(
        synthetic_results,
        official_domains=["example.invalid"],
        max_sources=5,
    )

    assert sources[0].published_date is not None
    assert sources[0].published_date.isoformat() == "2025-01-02"
    assert sources[1].published_date is None


def test_official_domains_match_subdomains_not_lookalikes() -> None:
    results = [
        RawSearchResult(
            title="Official",
            url="https://portal.rbi.org.in/doc",
            content="",
        ),
        RawSearchResult(
            title="Lookalike",
            url="https://rbi.org.in.example.invalid/doc",
            content="",
        ),
    ]

    sources = rank_and_dedupe_sources(
        results,
        official_domains=["rbi.org.in"],
        max_sources=5,
    )

    assert [source.tier.value for source in sources] == ["official", "other"]


def test_credible_result_count_deduplicates_urls() -> None:
    results = [
        RawSearchResult(
            title="Official",
            url="https://rbi.org.in/education#overview",
            content="",
        ),
        RawSearchResult(
            title="Same official page",
            url="https://rbi.org.in/education",
            content="",
        ),
    ]

    assert count_credible_results(results, ["rbi.org.in"]) == 1


def test_source_url_is_preserved_from_provider_result() -> None:
    original_url = "https://rbi.org.in/education#overview"
    source = rank_and_dedupe_sources(
        [RawSearchResult(title="Official", url=original_url, content="")],
        official_domains=["rbi.org.in"],
        max_sources=1,
    )[0]

    assert str(source.url) == original_url
