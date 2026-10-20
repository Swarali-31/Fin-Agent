# FinAgent

College project: four independent LangGraph-compatible agents for personal finance (Python).

This repository currently contains **shared foundations only** (config, LLM helper, Pydantic schemas, sample data). Agent implementations are not included yet.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Optional LLM provider extras, e.g.:
# pip install -e ".[dev,anthropic]"
cp .env.example .env
```

## Tests

```bash
pytest
```

Tests marked `live` require real API keys in `.env`.

## Integrated local app

From the repository root, configure `backend/.env` (or process environment):

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/finagent
# For real research sources:
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=your-backend-only-key
# For model-based planning and interpretation, also set:
LLM_PROVIDER=openai
LLM_MODEL=your-enabled-model
OPENAI_API_KEY=your-backend-only-key
```

Use the corresponding optional provider package (`.[openai]`, `.[anthropic]`, or `.[google]`) when configuring that provider. Existing local dependencies need no reinstall.

```bash
PYTHONPATH=src .venv/bin/python -m backend.app.db.migrate
PYTHONPATH=src .venv/bin/python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
# In another terminal:
cd frontend
npm run dev -- --host 127.0.0.1
```

Create/select a profile on Dashboard, add/import transactions on Expense Analysis, then use the specialist pages or describe a goal to Master Agent. Master Agent fetches stored transactions automatically and saves validated specialist results to the same history. Research works without a profile. Missing provider configuration is shown explicitly; no citations or successful executions are fabricated. Without an LLM, the existing deterministic financial calculations and fallback planner remain available and disclose their limitations.
