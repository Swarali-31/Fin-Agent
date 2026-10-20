# FinAgent cloud setup and deployment

## Architecture

The React browser calls FastAPI. FastAPI connects to Supabase **PostgreSQL** using a server-only database connection string. This integrates the application's existing password-account and HttpOnly-session system; it does not pretend to use Supabase Auth or store financial records in browser storage. Financial profiles, transactions, agent outputs, workflows, users and sessions are in the cloud database.

The application scopes every financial query to the signed-in user. The migration enables Row Level Security without public Data API policies; browser Supabase keys are unnecessary. Use the database owner/session-pooler connection from Supabase for the backend, never an anonymous browser key.

## Current cloud project

- Organization: FinAgent (Free).
- Project: FinAgent.
- Project URL: https://zzscmkduqomftjrpmyhs.supabase.co
- Region: Southeast Asia (Singapore), ap-southeast-1.
- Public Data API disabled; the application connects through its backend.
- The backend is connected through the SSL session pooler; both migrations are applied. Verified all application schema columns and RLS on all 10 application tables.
- The database password is kept only in the ignored backend configuration. No password or API key is recorded in this document.

## 1. Create the Supabase project

In [Supabase Dashboard](https://supabase.com/dashboard), create a project named `FinAgent` on your free organization. Choose the region you want your data stored in and set a strong database password. Account agreements and password creation must be completed by the account owner.

In the project's **Connect** dialog choose **Session pooler**, then copy the PostgreSQL URI. Session mode supports IPv4 and persistent Python connections; see [Supabase's connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres).

Put the URI in the ignored `backend/.env`, replacing the password placeholder with the URL-encoded database password:

```dotenv
DATABASE_URL=postgresql://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
SECURE_COOKIES=false
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=YOUR_BACKEND_ONLY_SEARCH_KEY
LLM_PROVIDER=google_genai
LLM_MODEL=gemini-3.5-flash-lite
GOOGLE_API_KEY=YOUR_BACKEND_ONLY_MODEL_KEY
```

For the prepared FinAgent project you can instead leave `DATABASE_URL` blank and set these backend-only values:

```dotenv
SUPABASE_DB_HOST=aws-0-ap-southeast-1.pooler.supabase.com
SUPABASE_DB_USER=postgres.zzscmkduqomftjrpmyhs
SUPABASE_DB_PASSWORD="YOUR_PRIVATE_DATABASE_PASSWORD"
```

The settings layer constructs the SSL connection URI and URL-encodes the password automatically. Neither password fields nor the constructed database URI are included when settings are serialized.

Do not paste secrets into source files, frontend variables, chat, or screenshots. An example URI is not a live connection. No `.env` files belong in Git or a container image.

## 2. Apply migrations

From the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m backend.app.db.migrate
```

This applies `001_initial_persistence.sql` and `002_accounts_and_ownership.sql` transactionally and records the migration filenames. It does not delete old financial records or assign existing unowned data to a newly registered user. For a database initialized manually before migration tracking existed, baseline the initial schema explicitly after verifying it matches; do not rerun initial CREATE TABLE statements against existing tables.

## 3. Run locally against the cloud database

```bash
PYTHONPATH=src .venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
# A second terminal:
cd frontend
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`. Signup creates a personal profile and takes the user straight to expenses. Add income/expenses or import CSV, save and analyze, then create a budget/report or use Master Agent. Login restores the user's account and cloud history.

Expense calculations and baseline budgets run through the existing specialist implementations without an LLM; their limitations remain explicit. Real financial research requires the Tavily key. Natural-language model planning/interpretation additionally needs a model key and its provider package, for example `pip install '.[openai]'`. Missing providers never produce fabricated sources or fake successful results.

## 4. Deploy after cloud verification

The Dockerfile builds React and runs FastAPI as a non-root user. FastAPI serves the React build and API from one origin so session cookies work without cross-site cookie workarounds.

- Build using the repository root as the Docker context.
- Configure the same `DATABASE_URL` and provider secrets in the host's environment/secret manager.
- Set `SECURE_COOKIES=true` behind the deployment host's HTTPS proxy.
- Set `CORS_ORIGINS=https://YOUR_APP_DOMAIN` to allow writes from that origin.
- Run `python -m backend.app.db.migrate` as an explicit release command before starting the new app version.
- The start command accepts the host's `PORT`, defaulting to 8000.
- Liveness endpoint: `/api/v1/health`. Validate database access through signup and saved expenses before calling the deployment ready.

No hosting service is selected and no application has been published by adding this configuration. Background workflows currently run inside the API process; deploy one persistent instance for this version. A process restart may interrupt an in-flight workflow; durable queues/restart recovery and email verification/password recovery are separate production-hardening work, not features claimed by this implementation.


## Beginner workflow and local development

The backend serves the production frontend on the same origin after `npm --prefix frontend run build`. Start it from the assignment directory:

```sh
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

For a separate frontend development server (5174 avoids an older 5173 process):

```sh
cd frontend
VITE_API_BASE_URL=/api/v1 FINAGENT_API_TARGET=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
```

Allow `http://127.0.0.1:5174` in backend `CORS_ORIGINS`. API keys belong only in ignored backend environment files. The deployed frontend has no provider keys.

Choose a profile/currency, upload a UTF-8 CSV, review detected columns, choose any ambiguous date/amount convention, resolve invalid/duplicate rows, and choose **Analyze my spending**. The preview does not save financial data. Existing transactions can be corrected; corrections invalidate the previous analysis. Budget Planning uses the latest current analysis and preserves a revision when the savings goal changes.

Refunds are explicit returned cash, included in money received and shown separately; they are not promised as recurring earnings. Transfers between owned accounts are stored but excluded from income/spending. Unknown expense categories are protected from automatic budget cuts until the user classifies them or explicitly chooses essential categories. Monthly averages cover every calendar month between the first and last cash-flow transaction, including empty months. The `cashflow-v2` analysis version invalidates earlier calculations without deleting history.

Search and model outages produce honest partial/error states. A Google 503 response is a provider availability issue; calculated totals remain available, and analysis can be retried without importing transactions again.

## Free Render deployment

`render.yaml` defines one Free Docker web service serving both the React UI and FastAPI, with Supabase retained as the database. Automatic deployment is disabled. Import this repository as a Render Blueprint, supply private credentials through Render's environment settings, and set CORS_ORIGINS to the exact HTTPS service URL before testing sign-in. No secrets are stored in the blueprint. Current model: gemini-3.5-flash-lite.

Render Free services sleep after 15 minutes without incoming traffic, so the first visit can be slow. Provider API quotas/billing are separate from hosting; Free hosting does not make Gemini or Tavily usage unlimited. Existing local records remain in Supabase. A live deployment requires the tested source to be pushed to GitHub and Render repository access to be authorized by the owner.
