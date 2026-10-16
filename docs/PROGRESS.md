# Progress

## 2026-10-15 — Budget Planning README review

- Reviewed `src/finagent/agents/budget_planning/README.md` against the budget graph, allocation code, and shared budget schemas; the documented behavior matches the implementation.
- Files changed: `docs/PROGRESS.md` only. No README or agent code changes.
- Commands: none; documentation review only, no tests run.
- Open issues: `docs/AUDIT.md` was not present during review.

## 2026-10-15 — Master-agent orchestrator

- Added a LangGraph workflow planner/executor with deterministic fallback routing, plan/DAG/input validation, concurrent independent steps, version checks, bounded retries and replans, dependent-step skipping, provenance-backed synthesis, and trace persistence through the repository boundary.
- Files changed: `backend/app/orchestrator/{__init__.py,graph.py,planning.py,schemas.py}`, `backend/tests/test_orchestrator.py`, and this progress log.
- Commands: `PYTHONPATH=src /Users/vanshikadhawan/Developer/assignment/.venv/bin/python -m pytest backend/tests -q`; `PYTHONPATH=src /Users/vanshikadhawan/Developer/assignment/.venv/bin/python -m pytest tests -q`.
- Results: backend tests **74 passed, 2 skipped**; root tests **30 passed**. Pylance diagnostics for the new orchestrator modules and test file reported no issues.
- Open issues: none for the requested scope; live LLM/search configuration and PostgreSQL persistence remain environment-dependent and were not exercised.

## 2026-10-15 — FastAPI v1 endpoints

- Added envelope-wrapped routes for health/agent registry, all four specialist adapters, background workflow create/poll/trace/list, profile transactions and sample data, expense analysis history/summary, budgets, research, and reports with JSON/Markdown download.
- Added API services, repository read/list operations, a default localhost CORS origin, consistent validation/not-found/conflict/persistence error mapping, and endpoint documentation.
- Files changed: `backend/app/api/{__init__.py,routes.py,responses.py}`, `backend/app/services/api.py`, `backend/app/main.py`, `backend/app/config/settings.py`, `backend/app/repositories/{base.py,postgres.py}`, `backend/tests/test_api.py`, `docs/API.md`, and this progress log.
- Commands: `PYTHONPATH=src /Users/vanshikadhawan/Developer/assignment/.venv/bin/python -m pytest backend/tests/test_api.py -q`; full backend and root suite results to follow after final validation.
- Results: focused API tests **11 passed**; full backend suite **74 passed, 2 skipped**; root suite **41 passed**. Pylance diagnostics for API modules and tests are clean. No new dependencies; endpoints use adapters and repository services; the orchestrator and agents were not changed.
- Open issues: PostgreSQL-backed request execution and real provider calls require environment configuration and were not exercised against remote services.

## 2026-10-15 — Frontend scaffold

- Added the React/Vite app shell, six title-only routes, responsive navigation, shared UI components, design tokens, and the envelope-aware API client with endpoint modules.
- Files changed: `frontend/` (tooling, lockfile, source, and `.env.example`) and this progress log.
- Commands: `cd frontend && npm test`; `npm run build`; `npm audit --audit-level=moderate`; browser viewport checks at 375px, 768px, and 1280px.
- Results: API client tests **3 passed**; production build succeeded; npm audit **0 vulnerabilities**; no horizontal overflow or title clipping at tested widths, and mobile drawer opens.
- Open issues: API base URL defaults to `/api/v1`; configure `VITE_API_BASE_URL` when not using the Vite proxy. Specialist/backend integration is intentionally not part of this scaffold.

## 2026-10-15 — Dashboard and Master Agent pages

- Implemented the API-backed dashboard (summary metrics/charts, workflows, agent registry, profile selection, explicitly requested sample data) and Master Agent task submission, polling, plan, trace, result, provenance, and source views. Wired only these two pages into the existing routes.
- Files changed: `frontend/src/pages/{Dashboard.jsx,MasterAgent.jsx,pages.test.jsx}`, `frontend/src/App.jsx`, `frontend/{package.json,package-lock.json,vite.config.js}`, `frontend/src/services/api.test.js`, `frontend/src/test-setup.js`, and this progress log.
- Commands: `cd frontend && npm test`; `npm run build`; `npm audit --audit-level=moderate`; browser viewport checks at 375px, 768px, and 1280px.
- Results: **10 tests passed**; production build succeeded; npm audit **0 vulnerabilities**; both pages fit the tested viewport widths without horizontal overflow.
- Open issues: current APIs do not return `is_sample` with profile summaries, expose stored profile transactions, or track realized savings. The UI preserves the sample badge for profiles created through its explicit sample action, labels budget savings as a planned target (not realized progress), and asks for transaction data in Master Agent context for financial workflows. The Add transactions link points to the still-stub Expense Analysis page, which was out of scope. No backend changes made.

## 2026-10-16 — End-to-end verification

- Fixes: connected the existing Financial Research and Reports pages to their routes; extended deterministic routing for “analyze my spending” tasks; preserved `is_sample` through expense-analysis persistence; persisted the complete workflow plan/trace/errors/sources for polling; changed missing page-level agent status to `unknown` rather than implying success; added `node_modules/` and `dist/` ignore rules.
- Files changed: `.gitignore`, `backend/app/orchestrator/{graph.py,planning.py}`, `backend/app/services/api.py`, `backend/tests/{test_api.py,test_orchestrator.py}`, `frontend/src/App.jsx`, `frontend/src/pages/{ExpenseAnalysis.jsx,BudgetPlanning.jsx,FinancialResearch.jsx,Reports.jsx}`, and this file.
- Startup commands (from the repository root unless noted):
  - Backend: `PYTHONPATH=src .venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000`
  - Frontend: `cd frontend && npm run dev -- --host 127.0.0.1`
- End-to-end checks: explicitly loaded sample data; Dashboard monthly income/expenses/surplus (`INR 85,000.00` / `INR 76,264.67` / `INR 8,735.33`) matched the raw profile summary. Expense analysis, budget revision, and report outputs matched their native agent results for versions and returned values/status. Research returned `search_not_configured` with zero sources consistently through page, API, and native call. A changed transaction changed the analysis version (`ea-c7079a4339c6` to `ea-f4b1c24b7693`); Budget Planning marked the prior budget stale and revised against the new version. The multi-agent workflow displayed a deterministic-fallback plan, expense-before-budget dependency, independent research, actual results, and claim provenance; no sources were fabricated. Regression tests cover bounded exception retries, non-retryable configuration failures, stale-budget replanning, sample flags, and complete workflow polling results.
- Commands/results:
  - `PYTHONPATH=src .venv/bin/python -m pytest backend/tests -q` — **74 passed, 2 skipped**.
  - `PYTHONPATH=src .venv/bin/python -m pytest tests -q` — **42 passed**.
  - `cd frontend && npm test && npm run build` — **24 tests passed**; Vite production build succeeded.
  - `git diff --check` — passed. Ignore checks confirmed `.env`, `node_modules/`, `dist/`, and `build/` are ignored. Common credential-pattern scans, Vite-secret-variable scans, and success-fallback scans found no matches in the scanned source.
- Untested: real PostgreSQL/migration execution (no database configured); real LLM and Tavily requests (no provider keys configured). Live persistence verification used an isolated in-memory SQLite repository injected into the local app process; it did not connect to or modify a remote database. Agent-exception/retry behavior was exercised with mocked adapters in the test suite, not against a live provider.
- Repository note: generated dependency/build paths were already staged in the worktree before this verification. Ignore rules now prevent future untracked additions, but the staged index was intentionally left untouched.

## 2026-10-16 — Stored-profile integration completion

- Added profile creation/listing and stored transaction reads; Dashboard can create/select a real empty profile before imports. Existing CSV/manual transaction entry remains in use.
- Removed manual JSON context from Master Agent. A selected profile ID is hydrated from the repository; the existing LangGraph planner and real specialist adapters still execute every task. Workflow expense/budget/research/report outputs now populate shared persisted histories. Research remains profile-optional and its page displays persisted history.
- Added freshness checks before budget/report execution and before workflow results are saved; stale workflows fail explicitly. Analysis versions are independent of transaction order. Sample loading refuses existing profiles to protect real financial data.
- Added an explicit transactional PostgreSQL migration command with version tracking; normalized supported PostgreSQL URL formats. Backend reads root and backend environment files and accepts both local frontend origins plus CSV/JSON-array CORS settings.
- Validation: `PYTHONPATH=src .venv/bin/python -m pytest backend/tests tests -q` — **122 passed, 2 skipped**; `cd frontend && npm test && npm run build` — **24 passed**, production build succeeded. Added native expense→budget→report API integration, stale-input/in-flight-change, profile history, canonical-version and settings coverage. Persistence integration tests use isolated SQLite, not a fake application repository. `git diff --check` passed.
- Live HTTP checks: backend starts on 127.0.0.1:8000; frontend starts on 127.0.0.1:5173 and returns HTTP 200; `/api/v1/health` succeeds directly and through Vite's proxy.
- Blockers: no DATABASE_URL, no PostgreSQL listener on localhost:5432; isolated initdb was blocked by sandbox shared-memory syscall permissions, including after localhost network access was granted. PostgreSQL SQL execution remains unverified. Migration command correctly fails with an actionable error when DATABASE_URL is absent. No provider credentials configured; live LLM/Tavily requests unverified. Tavily SDK is present; optional LangChain OpenAI/Anthropic/Google provider packages are absent and should be installed only for the configured provider.
- No dependencies installed, no original financial records deleted, no commits or pushes. Original agent algorithms, schemas, UI routes and existing API payloads retained.

## 2026-10-16 — Accounts, guided workspace, cloud preparation

- Added forest-green/cream public landing page, login/signup pages, protected workspace routing, cookie-session client handling, account switching/signout, and automatic personal-profile selection. Reused the existing password-account/ORM ownership work already present in the worktree.
- Signup creates a personal profile; the expense screen supports manual/CSV entry, save-and-analyze, and saved transaction history. Specialist pages keep profile controls in advanced settings and provide clear next-step links. Master Agent uses saved profile context with suggested tasks, retaining the real LangGraph/specialist implementations.
- Added `002_accounts_and_ownership.sql`: account/session tables, financial ownership columns/indexes, and RLS blocking public Data API access. Credentials and database access stay backend-only. Existing unowned records are preserved, not automatically assigned to new accounts.
- Added same-origin serving for the production React build, a non-root multi-stage Dockerfile, secret exclusions, Supabase session-pooler connection settings, and `docs/DEPLOYMENT.md`. Deployment has not been published. A private ignored `backend/.env` template is prepared without credentials.
- Focused functional check: isolated SQLite account-flow test passed, including signup/login/logout, real expense→budget→report execution, and cross-user denial of transaction/report/workflow/trace access. Production build and Python compilation passed. Broad regression/live-provider checks are deferred as requested; no complete-production-readiness claim is made.
- Supabase: created the requested free FinAgent organization through the user's signed-in dashboard. Project form prepared as FinAgent with the Data API disabled (the backend uses direct PostgreSQL). The account owner must enter the project password and submit creation. Actual cloud connection/migrations remain pending that step and the private Session pooler URI. LLM/search provider credentials are also absent; no fake successes or sources substituted.

### Cloud connection completed

- User created the FinAgent project (`zzscmkduqomftjrpmyhs`) in the free FinAgent organization, region Singapore. Account owner supplied the database credential for backend-only configuration; no credential was added to source or frontend variables.
- Applied both SQL migrations to live Supabase successfully. Verified `SELECT 1`, both migration records, all application schema columns, and RLS on **10/10 application tables**. Backend restarted against Supabase; private credentials remain in ignored `backend/.env` with owner-only file permissions. No test accounts/financial transactions were seeded into the cloud project.
- Final focused account-isolation/real-workflow check passed against isolated SQLite; backend-only Supabase password encoding check passed. Final production build succeeded. Full regression/live-provider suites remain deferred as requested.
- Dashboard summary reads no longer invoke LLMs or append duplicate analyses; explicit expense actions invoke the existing real agent on stored transactions.
- Still needed for full provider features: Tavily credential, and configured LLM provider/model/key plus its provider package. No live provider call or public hosting deployment is claimed.

### 2026-10-16 usability follow-up
- Reports now download authenticated PDF documents (ReportLab), alongside JSON/Markdown; PDF preserves source versions, warnings, budgets, and citations.
- Added Profile page for account details, financial profile selection/creation, and expense import entry point. Master Agent is last in navigation.
- Added plain-language Master Agent summaries and workflow guide, plus explicit optional monthly savings target. Fixed missing budget allocation labels.
- Added five schema-validated synthetic INR CSV scenarios under `sample_imports/` with totals and upload instructions.
- Configured backend-only Tavily key; live emergency-fund query returned official SEBI/RBI sources. AI synthesis still requires a configured model/provider key; searches retain honest partial status when synthesis is unavailable.
- Current updated local preview: http://127.0.0.1:8001 (backend serves production frontend). Existing older processes on 8000/5173 could not be stopped from this session.
- Final checks: Python 124 passed / 2 skipped; frontend 24 passed; production build passed. Browser verified authenticated PDF download, working cloud profile list and a live research run with real citations.
- Live full workflow revealed duplicate immutable budget IDs failing persistence on repeated goals. Fixed saves to reuse the existing record (including insert-race recovery) and added regression coverage (8 persistence/account tests passed). Rerun `07802ceb-ed80-4802-8d0d-804e9dcea203` persisted all outputs and trace without errors: savings INR30,000, five research sources, flagged report because AI synthesis/data gaps remain.

### Gemini expense-analysis connection
- Configured backend-only Google Gemini credentials and selected `google_genai` / `gemini-3.1-flash-lite` after successful live structured-output and full expense-agent calls. Gemini 3.8 returned provider high-demand errors; Gemini 2.5 returned unavailable-to-new-users errors.
- Installed the existing Google optional extra dependency; deployment image now includes Google integration. Normalized the `google` alias and bounded provider request time/retries.
- Fixed Expense Analysis UI to actually show returned spending patterns; added explicit rerun of stored transactions without reuploading files.
- Provider outages now produce safe, actionable messages while preserving verified financial totals.
- Verification: real 22-transaction demo returned expense status success, AI spending insight and no limitations. Python suite 127 passed / 2 skipped; frontend 25 passed; production build passed; dependency check passed.
- Browser confirmation after restart: Expense Analysis reran saved demo transactions and displayed `Analysis success`, a genuine Gemini insight, and clarification questions. Research also returned three genuine cited findings; partial status reflected an explicit evidence limitation, not missing LLM configuration.

### Beginner-friendly import and agent integration
- Added server-side bank CSV preview, column mapping, explicit date/amount conventions, row exclusions, duplicate review, refunds/transfers and saved transaction corrections. Preview does not save data.
- Expense results now expose period totals and calendar-month averages; transfers are excluded, refunds disclosed, and calculation-version hashes reject old results.
- Guided budgets use current persisted analysis, protect uncategorized costs, accept revised goals on unchanged analysis and retain revision history. Master reuses only current validated analysis and exposes a simpler execution timeline.
- Research uses genuine Tavily sources with safe provider errors; clearer beginner forms and royal-blue/green styling preserve existing agent implementations. Profile creation no longer changes the selected profile after navigating away.
- Verification: Python 146 passed / 2 skipped; frontend 29 passed; production build and git diff whitespace check passed.
- Live browser: bank CSV required date confirmation before saving; 10 demo rows produced INR162,000 received, INR52,000 spent and INR110,000 remaining across two months. INR2,000 refunds were disclosed and own-account transfers excluded. Budget goal INR70,000 returned INR15,000 shortfall; revising to INR30,000 persisted revision 2 as feasible. Tavily returned RBI/NISM sources. Gemini was temporarily unavailable, so analysis/research honestly retained partial status rather than fabricated AI output.
- Local preview remains port8001; dev frontend port5174 proxies to8001. Credentials remain backend-only in ignored environment configuration.

### Restore live Gemini answers and explain budget provenance
- Confirmed the configured gemini-3.1-flash-lite returned HTTP503 with a valid key. Tested structured responses from available gemini-3.5-flash-lite and gemini-3.6-flash; selected gemini-3.5-flash-lite in backend-only configuration and restarted port8001.
- Real expense agent returned success with two insights; browser rerun of saved 32-row profile persisted Analysis success. Real Tavily/Gemini research generated a cited finding; partial status in that test reflected an evidence gap, not model disconnection.
- Traced displayed INR161,000/81,000/80,000 monthly figures to INR322,000 received and INR162,000 spent over two months. This profile combines two demonstration datasets. No transactions were deleted or silently changed.
- Budget screen now names the selected profile, transaction count, period total/divisor arithmetic, refund treatment and difference between deterministic calculations and AI explanation.
- Checks: targeted Python17 passed/1 skipped, frontend29 passed, production build passed, whitespace check passed.

### Research chat and transaction selection
- Replaced the research form/results layout with user/assistant messages, cited replies, contextual follow-ups, New chat and expandable saved questions/sources. Conversation input is bounded to 12 messages and explicitly treated as context rather than evidence by the existing research agent.
- Added account-scoped selected-transaction soft deletion and undo without a destructive migration. Removed rows no longer feed current analysis or CSV duplicate checks. Existing histories are preserved and source hashes invalidate outdated budgets/analyses.
- Expense transaction management supports select-all, individual selection, delete and undo, plus recurring-payment corrections. Duplicate and data-gap explanations are concise and collapsed; transaction dates distinguish repeated monthly questions.
- Verification: Python148 passed/2 skipped (one existing workflow timing test passed on isolated and full rerun); frontend31 passed; production build and diff whitespace check passed. Live research chat returned an emergency-fund explanation citing RBI/SEBI; follow-up context checked in UI and tests. No personal transactions were deleted during verification.

### Green sidebar and compact reports
- Restored green sidebar styling; removed Profile from sidebar while retaining account access through the avatar.
- Removed Budget Planning's provenance/explanation section as requested. Reports retain validation status and a short summary, with full content behind View full report and PDF export unchanged.
- Live Master demo exposed Gemini planner omitting required specialist input references despite receiving a valid stored profile. Added explicit per-agent input-reference contracts to the planner prompt, preserving all plan validation and actual specialist execution.
- Corrected demo run 3edcafe1-70f6-44b0-8036-9a0b55c70938 executed Expense Analysis, Financial Research, Budget Planning and Financial Report with a INR30,000 goal. Partial specialist statuses are retained honestly for feasibility/evidence limitations.
- Verification: frontend31 passed, targeted orchestration/API32 passed, production build passed and whitespace check passed. Stabilized existing SQLite workflow-mutation test by synchronizing its mutation before polling the shared test connection.
