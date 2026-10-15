# FinAgent Repository Audit

Audit date: 2026-10-15

## Scope and repository snapshot

This audit describes the checked-out repository, not the GitHub repository's
unfetched state. It is currently a Python `src`-layout project containing four
agent packages, shared Pydantic schemas, sample data, examples, and tests.
There is no implemented HTTP backend, frontend, master agent/orchestrator, or
persistence layer in this checkout.

The root [README.md](../README.md) says that the repository contains "shared
foundations only" and that agent implementations are not included. That
description is stale: all four agent packages, their tests, and example runners
are present. The root README's setup instructions and test command otherwise
describe the existing packaging/test workflow.

### Files and configuration inspected

- `README.md`
- `pyproject.toml` (no separate `requirements*.txt` was found)
- `.gitignore`
- `.env.example`
- `src/finagent/config.py` and `src/finagent/llm.py`
- Shared schemas in `src/finagent/schemas/`
- Four packages in `src/finagent/agents/`
- Four `examples/run_*.py` runners and test files under `tests/`

No Dockerfile, Docker Compose file, GitHub Actions workflow, or other CI
configuration was found. The initial repository tree also contained generated
`.pytest_cache`, bytecode caches, and `src/finagent.egg-info`; these are not
application source or integration layers.

## Git state

Read-only Git commands returned:

```text
git status --short:
?? docs/

git branch --show-current:
main

git --no-pager log --oneline -10:
9d62edc budget_planning  agent done
b36087e financial_research agent done
16e14a8 Add budget planning improvements
58f9b91 first agent done
b2b019c Initial project structure
```

The only reported uncommitted path is the untracked `docs/` directory. At audit
time, it contains `PROGRESS.md` (from the preceding documentation review) and
this audit file. No tracked source changes were reported. The existing
`docs/PROGRESS.md` was left unchanged to respect the instruction not to modify
existing files.

## Agent inventory

All four packages expose callable Python graph and runner APIs. They are
standalone agent implementations, not integrated into a backend or a shared
master-agent workflow. No agent has a database dependency.

### Expense Analysis Agent

- **Public API:** `build_expense_analysis_graph(llm=None)` and
  `run_expense_analysis(request, llm=None)` in
  `src/finagent/agents/expense_analysis/graph.py`; additionally exports
  deterministic helpers `compute_expense_metrics`, `detect_recurring`,
  `find_data_gaps`, and `ExpenseMetrics` from its `__init__.py`.
- **Request / result schemas:** `ExpenseAnalysisRequest` -> `ExpenseAnalysisResult`
  in `src/finagent/schemas/expense.py`.
- **Required input:** `ExpenseAnalysisRequest.profile`, a
  `FinancialProfile` with at least one transaction. Transactions contain a
  positive `Money` amount, date, type, and description; expense category and
  recurring status may be unknown and are surfaced as data gaps.
- **Optional context:** `FinancialProfile.savings_goal`; transaction merchant,
  expense category, and recurring marker are optional. `llm` is optionally
  injected. There are no tools other than the structured LLM call.
- **Versions:** `ExpenseAnalysisResult.analysis_version` is generated as
  `ea-...` from the profile's JSON representation by
  `compute_expense_metrics` (`calculations.py`).
- **Dependencies/injection:** deterministic calculations are local Decimal
  operations; qualitative interpretation uses an injected structured LLM or
  lazily calls `finagent.llm.get_llm()`. No search or DB dependency.
- **Status/error model:** common `AgentResultBase` carries `status` (`success`,
  `partial`, or `failed`), `errors`, `limitations`, and `generated_at`.
  Invalid input/calculation/execution returns a failed result; LLM failure
  retains deterministic data and returns partial with a limitation.
- **Tests / CLI:** `tests/agents/test_expense_calculations.py` and
  `tests/agents/test_expense_graph.py`; live LLM smoke test is marked
  `live`. CLI/example: `examples/run_expense_analysis.py`.
- **Integration status: partial.** Callable request/result and runner exist
  (`expense_analysis/graph.py:build_expense_analysis_graph`,
  `:run_expense_analysis`), but no backend service/HTTP endpoint or master
  agent invokes them.

### Budget Planning Agent

- **Public API:** `build_budget_graph(llm=None)`,
  `run_budget_planning(request, llm=None)`, and
  `revise_budget(previous, new_analysis, llm=None)` in
  `src/finagent/agents/budget_planning/graph.py`; deterministic
  `baseline_allocation` and `check_feasibility` are also exported.
- **Request / result schemas:** `BudgetRequest` -> `BudgetPlan` in
  `src/finagent/schemas/budget.py`.
- **Required input:** a source `ExpenseAnalysisResult` with a non-failed
  status, summary, and non-empty `analysis_version`; invalid/missing input
  produces a structured failed plan.
- **Optional context:** optional `savings_goal`, `essential_categories`, and
  currency override on `BudgetRequest`. `llm` may be injected; `llm=False`
  selects deterministic baseline-only operation. The planner does not search
  or persist to a DB.
- **Versions:** result fields include `budget_id`, `revision`, and
  `source_analysis_version`. Budget ID is a deterministic `bp-...` version
  based on source analysis version, target, effective preferences, and
  revision (`graph.py:_versioned_id`). Revision metadata contains parent and
  source-version information plus category deltas (`RevisionInfo`).
- **Dependencies/injection:** Decimal deterministic allocation and
  feasibility; optional structured LLM for discretionary adjustments. The
  LLM is injected or lazily obtained from `finagent.llm.get_llm()`. No search
  or DB dependency.
- **Status/error model:** common `AgentResultBase` status/errors/limitations.
  Input, allocation, and execution failures return a failed plan. A missing or
  invalid LLM proposal retains the deterministic baseline and reports a
  limitation/partial status.
- **Tests / CLI:** `tests/agents/test_budget_allocation.py` and
  `tests/agents/test_budget_graph.py`. CLI/example:
  `examples/run_budget_planning.py`.
- **Integration status: partial.** The callable budget API consumes the
  expense result (`budget_planning/graph.py:run_budget_planning`,
  `:revise_budget`), but no service adapter, endpoint, or orchestrator wires it
  to expense analysis.

### Financial Research Agent

- **Public API:** `build_research_graph(llm=None, search_provider=None)` and
  `run_financial_research(request, llm=None, search_provider=None)` in
  `src/finagent/agents/financial_research/graph.py`. Search protocol, Tavily
  implementation, and provider factory are exported from `__init__.py`.
- **Request / result schemas:** `ResearchRequest` -> `ResearchResult` in
  `src/finagent/schemas/research.py`.
- **Required input:** `question` string; the schema does not set an explicit
  non-empty constraint. Request defaults jurisdiction to `"IN"` and maximum
  sources to 5, bounded from 1 to 10.
- **Optional context:** `preferred_domains`; injectable structured LLM and
  `SearchProvider`. Without an injected provider, Tavily is resolved lazily
  using settings. No DB dependency.
- **Versions:** no research-result version field is defined. Sources carry
  `source_id`, provider-returned `published_date` if present, and
  `retrieved_at`.
- **Dependencies/injection:** query planning and synthesis use the injected or
  configured LLM. Search uses the injectable `SearchProvider` protocol, or
  `TavilySearchProvider` from the official `tavily-python` dependency. Search
  reads `SEARCH_PROVIDER`, `TAVILY_API_KEY`, `SEARCH_TIMEOUT_SECONDS`,
  `SEARCH_MAX_RESULTS`, and `OFFICIAL_DOMAINS`. No DB dependency.
- **Status/error model:** common `AgentResultBase`; configuration errors return
  failed with structured `AgentError` (including `search_not_configured`).
  Search failures after retry return failed if no query succeeded or partial
  if some succeeded; synthesis/no-result limitations are surfaced without
  fabricating findings.
- **Tests / CLI:** `tests/agents/test_research_search.py`,
  `tests/agents/test_research_source_ranking.py`, and
  `tests/agents/test_research_graph.py`; live Tavily smoke test is marked
  `live`. CLI/example: `examples/run_financial_research.py`.
- **Integration status: partial.** The graph accepts an injectable provider
  (`financial_research/graph.py:build_research_graph`) and returns the shared
  result type (`:run_financial_research`), but no backend adapter, endpoint,
  or orchestrator calls it.

### Financial Report Agent

- **Public API:** `build_report_graph(llm=None)` and
  `run_financial_report(request, llm=None)` in
  `src/finagent/agents/financial_report/graph.py`; pure validation helpers
  are exported from `__init__.py`.
- **Request / result schemas:** `ReportRequest` -> `FinancialReport` in
  `src/finagent/schemas/report.py`.
- **Required input:** upstream `ExpenseAnalysisResult` and `BudgetPlan`.
  Their versions and arithmetic/currency consistency are validated before
  composition.
- **Optional context:** research result and expected analysis version on
  `ReportRequest`; injected structured LLM. Research is optional but absent,
  failed, or partial research becomes a validation warning. `llm=False` uses a
  deterministic qualitative template. No search or DB dependency.
- **Versions:** `FinancialReport.report_version`, plus
  `source_versions.analysis_version`, `source_versions.budget_id`, and
  `source_versions.budget_revision`. Report version is a deterministic
  `fr-...` hash over analysis/budget versions and normalized research content
  (`graph.py:_report_version`).
- **Dependencies/injection:** qualitative composition uses an injected or
  configured LLM; financial figures, research findings, sources, and
  assumptions are copied from validated inputs. No search or DB dependency.
- **Status/error model:** `validation_status` is valid/flagged/rejected;
  rejected reports have failed `status` and no sections/version, warnings
  produce a partial report, and otherwise status is success unless composition
  fallback adds a limitation. The result uses common errors/limitations plus
  `ValidationIssue` codes.
- **Tests / CLI:** `tests/agents/test_report_validation.py` and
  `tests/agents/test_report_graph.py`. CLI/example:
  `examples/run_financial_report.py`.
- **Integration status: partial.** It consumes shared upstream results
  (`financial_report/graph.py:run_financial_report`) and validates their
  version linkage, but there is no backend adapter, endpoint, or orchestration
  flow to provide these inputs.

## Shared schemas, money, versions, and settings

- Shared schemas are in `src/finagent/schemas/`: `common.py`, `financial.py`,
  `expense.py`, `budget.py`, `research.py`, and `report.py`.
- `Money.amount` is a non-negative `Decimal`, quantized to two decimal places
  with half-up rounding; `SignedMoney.amount` permits negative values.
  JSON serialization emits monetary amounts as strings. Floats are rejected
  as monetary inputs. `CurrencyCode` is currently an alias for `str`, with a
  validator enforcing three uppercase letters; transaction/profile/summary
  models carry the currency separately from each monetary amount.
- `compute_version(prefix, payload)` in `schemas/common.py` serializes
  canonical sorted JSON (Decimals serialized as two-place strings), computes
  SHA-256, and returns the prefix plus the first 12 hex characters. Expense
  analysis uses prefix `ea`, budget uses `bp`, and report uses `fr`. Research
  defines no version field.
- `src/finagent/config.py` defines cached `get_settings()` and `Settings`,
  loading `.env` with `extra="ignore"`. The exact configured environment
  variables in `.env.example` are:
  `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TEMPERATURE`,
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
  `SEARCH_PROVIDER`, `TAVILY_API_KEY`, `SEARCH_MAX_RESULTS`,
  `SEARCH_TIMEOUT_SECONDS`, and `OFFICIAL_DOMAINS`.
- `src/finagent/llm.py:get_llm()` supports providers `anthropic`, `openai`,
  `google`, and `google_genai`, with optional corresponding LangChain provider
  packages. API keys are read from backend process environment or `.env`;
  none are embedded in source or `.env.example`.
- Settings are global/lazily cached in the current implementation; agents
  expose LLM and, for research, search-provider injection, but there is no
  common per-request settings/dependency-injection container.

## Frontend, backend, and persistence inventory

- **Frontend:** no React, Vite, or other frontend application/package found.
- **Backend:** no `backend/` package, FastAPI app, router, HTTP endpoint, or
  service/adapter layer found.
- **Master agent:** no master-agent or multi-agent graph/orchestrator found.
- **Database:** no SQLAlchemy/ORM models, Supabase client/schema, PostgreSQL
  integration, migration directory, Alembic configuration, Prisma schema, or
  repository layer found.
- **Deployment/CI:** no Docker/Compose files or CI workflow found.
- The only persistence-like artifacts are generated Python package metadata;
  they are not application database models.

## Baseline test result

Command run from the repository root:

```text
PYTHONPATH=src /Users/vanshikadhawan/Developer/assignment/.venv/bin/python -m pytest -q
```

Output:

```text
.........................s...............................s.............. [ 94%]
....                                                                     [100%]
74 passed, 2 skipped in 0.75s
```

The two skipped cases are live provider smoke tests requiring API keys:
expense-analysis LLM and Tavily research. No test failures were reported.
This is the observed local baseline; no tests or existing source files were
changed for the audit.

## Integration proposal (not implemented)

### Package/import strategy

Keep the existing root `pyproject.toml` and `src/finagent` package as the
single package definition; do not add a competing `pyproject.toml` under a
future backend. The root project already uses setuptools package discovery
from `src` and declares `finagent` as its distribution. Install it into the
backend's environment with `pip install -e <repository-root>` during local
development, or build/install the same root distribution in deployment. The
backend then imports the public APIs from `finagent.agents.*`. Avoid relying on
runtime `sys.path` mutation or `PYTHONPATH` in production.

### Adapter/service list

Implement thin backend-owned adapters/services that validate and translate
HTTP DTOs into the existing agent schemas, invoke the public APIs, and map
results/errors without duplicating agent calculations:

1. **ExpenseAnalysisAdapter** — `FinancialProfile`/`ExpenseAnalysisRequest` to
   `run_expense_analysis`.
2. **BudgetPlanningAdapter** — existing `ExpenseAnalysisResult` plus goal and
   preferences to `run_budget_planning` or `revise_budget`.
3. **FinancialResearchAdapter** — `ResearchRequest` to
   `run_financial_research`; inject the configured search provider when
   appropriate.
4. **FinancialReportAdapter** — validated expense, budget, and optional
   research results to `run_financial_report`.
5. **Master-agent/orchestration service** — explicitly sequence the above
   operations and handle branch/partial/failure policy; this does not exist
   yet and should not be inferred from the independent graphs.
6. **Profile/transaction repository and persistence service** — backend-owned
   interface for reads/writes; no repository exists in the current tree.

Keep HTTP route handlers thin. Preserve schema/status/error boundaries and
serialize monetary values as decimal strings. Do not expose LLM/search secrets
to a browser or use `VITE_` variables for credentials.

### Database approach

No database models or migrations exist to reuse. If PostgreSQL/Supabase is
selected, make persistence backend-owned: define user/profile/transaction
storage and migration/versioning strategy there, and persist validated
canonical profile inputs and agent outputs as appropriate. Reuse the existing
Pydantic schemas for validation/transport rather than treating them as ORM
models; keep Decimal-to-string API serialization explicit. Do not place
database access in `src/finagent/agents`.

### Risks and open questions

- The root README contradicts the implemented repository state.
- Backend, UI, endpoints, orchestration, auth/ownership, and DB are all absent;
  integration readiness therefore remains partial, not end-to-end.
- Select the intended backend packaging/deployment layout before adding code;
  retain the root project as the sole `finagent` package definition.
- Decide whether agent execution should be synchronous or queued/background.
  Research performs external search and agents may invoke remote LLMs, so HTTP
  timeouts, retries, cancellation, and idempotency need explicit policies.
- Decide user/profile ownership, transaction retention, consent, deletion, and
  sensitive financial-data access controls before persistence/API work.
- Decide how production settings are injected per environment/request and how
  provider configuration errors are mapped to HTTP responses. Never return
  provider secrets or raw sensitive profile data in error payloads.
- Define lifecycle/storage semantics for `analysis_version`, `budget_id`,
  `source_analysis_version`, and `report_version`; research currently has no
  version field.
- Confirm whether Supabase is accessed through PostgreSQL directly or its
  service API, and select a migration/tooling owner. No such choice is encoded
  in the current repository.
