# Financial Research Agent

The Financial Research Agent accepts a shared `ResearchRequest` and returns a
shared `ResearchResult` containing evidence-backed financial education,
retrieved `SourceMetadata`, structured errors, limitations, and a fixed
educational disclaimer. It does not provide personalized investment advice,
make budgets, or generate reports.

## Interface

```python
from finagent.agents.financial_research import run_financial_research

result = run_financial_research(request)
```

`build_research_graph(llm=None, search_provider=None)` creates the compiled
LangGraph `StateGraph`. Inject a LangChain chat model and a `SearchProvider`
for deterministic tests or alternate deployments. With no injected provider,
the graph lazily constructs the configured Tavily provider.

## Search tool contract

`SearchProvider.search(query, max_results, include_domains=None)` returns a
list of `RawSearchResult(title, url, content, published_date)`. It raises
`SearchError` for an operational query failure and `ConfigurationError` for
missing or unsupported provider configuration. The built-in
`TavilySearchProvider` uses the official `tavily-python` client, the
`TAVILY_API_KEY` setting, and `SEARCH_TIMEOUT_SECONDS`.

To add a provider, implement the `SearchProvider` protocol and inject the
instance into `run_financial_research`/`build_research_graph`. Do not add
development fakes to application source. Register a selectable provider
through `get_search_provider` if it should be configured by `SEARCH_PROVIDER`.

`OFFICIAL_DOMAINS` is a comma-separated list of official domains. RBI, SEBI,
and NISM domains are included by default. Search first restricts queries to
those domains; if fewer than two official results are found, it performs a
general search. Results are deduplicated by URL and official sources are ranked
first. Source dates are set only from a date returned by the provider.

## Graph nodes

1. `plan_queries` asks for one to three structured educational search queries
   and an advice-request flag. If planning fails, the original question is
   used. Personalized stock-picking requests use a neutral educational query.
2. `search_official` searches only configured/default official domains.
3. `search_general` runs when official results are insufficient.
4. `rank_and_dedupe` assigns source IDs after filtering and deterministic
   official-first ordering.
5. `synthesize` requests structured findings and limitations using only the
   retrieved sources.
6. `verify` drops findings with missing or unknown source IDs and rejects
   prescriptive buy/sell statements.
7. `assemble` adds the fixed educational disclaimer and returns the result.

## Failure modes

- Missing Tavily key or unsupported provider returns `status="failed"` and
  `search_not_configured`.
- A failed query is retried once. Persistent failures return an
  `AgentError(search_failed)`, skip synthesis, and produce `failed` if no query
  succeeded or `partial` when some succeeded.
- Empty/unusable results produce no findings and a `no_sources_found`
  limitation. If synthesis produces no verifiable findings, a
  `no_verified_findings` limitation is returned.
- Query-planning failure falls back to the raw question. Synthesis failure
  preserves the retrieved sources and returns a `partial` result.
- Personalized advice requests are reframed as general education and include a
  `personalized_advice_reframed` limitation. The output does not recommend
  specific securities.

## Configuration and execution

Set these values in the environment or `.env`:

```dotenv
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your-tavily-key
SEARCH_TIMEOUT_SECONDS=30
OFFICIAL_DOMAINS=rbi.org.in,sebi.gov.in,nism.ac.in
LLM_PROVIDER=your-provider
LLM_MODEL=your-model
```

The example performs real searches using `sample_research_question()`:

```bash
python examples/run_financial_research.py
pytest tests/agents/test_research_*.py
```

The live Tavily smoke test is marked `live` and runs only when
`TAVILY_API_KEY` is set. There are no fake provider outputs in the example.
