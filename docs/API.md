# FinAgent HTTP API

All endpoints use the `/api/v1` prefix. Responses use `ResponseEnvelope`:

```json
{
  "request_id": "request-id",
  "status": "ok",
  "data": {},
  "warnings": [],
  "error": null
}
```

Errors use `status: "error"` and an `error` object with `code`, `message`, and
optional `details`. Request validation and malformed bodies return 422;
missing records return 404; rejected report inputs and transaction conflicts
return 409; unavailable persistence or required provider configuration returns
503. Money is passed and returned using the shared schemas' decimal strings.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | API health |
| GET | `/agents` | Agent registry, capabilities, and integration status |
| POST | `/agents/expense-analysis/run` | Run expense analysis (`ExpenseAnalysisRequest`) |
| POST | `/agents/budget-planning/run` | Create budget (`BudgetRequest`); optional `profile_id` query persists it |
| POST | `/agents/budget-planning/revise` | Revise budget (`previous`, `new_analysis`); optional `profile_id` query persists it |
| POST | `/agents/financial-research/run` | Run financial research (`ResearchRequest`) |
| POST | `/agents/financial-report/run` | Validate and compose a report (`ReportRequest`); optional `profile_id` query persists it |
| POST | `/workflows` | Start background workflow (`task`, optional object `context`); returns 202 and `run_id` |
| GET | `/workflows/{run_id}` | Poll workflow status/result |
| GET | `/workflows/{run_id}/trace` | Read append-only trace |
| GET | `/workflows` | Paginated workflow runs; optional `status` filter |
| POST | `/profiles/{profile_id}/transactions` | Add JSON transactions or `text/csv`; a validation error lists row errors and saves none |
| POST | `/profiles/{profile_id}/sample-data` | Explicitly create sample profile/transactions; response and records set `is_sample: true` |
| GET | `/profiles/{profile_id}/summary` | Calculate and persist the latest profile summary through the expense adapter |
| GET | `/profiles/{profile_id}/expense-analyses` | Paginated analysis history |
| GET | `/profiles/{profile_id}/expense-analyses/latest` | Latest expense analysis |
| GET | `/budgets` | Paginated budgets; optional `profile_id` filter |
| GET | `/budgets/{budget_id}` | Budget detail by budget ID or storage ID |
| GET | `/budgets/{budget_id}/history` | Revision lineage |
| GET | `/research` | Paginated research runs; optional `profile_id` filter |
| GET | `/research/{research_id}` | Research run detail |
| GET | `/reports` | Paginated reports; optional `profile_id` filter |
| GET | `/reports/{report_id}` | Report detail |
| GET | `/reports/{report_id}/download?format=json\|markdown` | Envelope-wrapped downloadable report content |

List endpoints accept `page` (default 1) and `page_size` (default 20, max
100); list response data contains `items`, `page`, `page_size`, and `total`.
Persistence-backed profile, history, list, detail, and workflow operations
require `DATABASE_URL`. The app starts without it. Research additionally
requires a configured search provider/key unless a provider is injected by the
host application. Configure CORS through `CORS_ORIGINS`; the default is
`http://localhost:5173`.

Markdown download is rendered from the report's stored summary, qualitative
sections, and research findings. PDF is not offered because no PDF renderer is
installed or configured.

## Stored profile integration

- `POST /profiles` with `{ "profile_id": "my-profile", "currency": "INR" }` creates an empty profile (201); duplicate IDs return 409.
- `GET /profiles` lists profile IDs, currencies and sample flags.
- `GET /profiles/{profile_id}/transactions` returns saved native transactions.
- `POST /agents/expense-analysis/run` also accepts `{ "profile_id": "my-profile" }` to analyze stored transactions.
- `POST /workflows` accepts `{ "task": "Generate a financial report", "context": { "profile_id": "my-profile" } }`. Stored data overrides browser transaction/upstream snapshots; missing financial inputs are rejected by the existing planner. Valid specialist outputs are saved to the shared histories; profile changes during execution fail the run as stale.
- Budget/report endpoints with `?profile_id=...` resolve current persisted upstream inputs and reject stale snapshots (409).
- Research run accepts optional `?profile_id=...` for profile-linked history; omission continues to support profile-free research.
