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
