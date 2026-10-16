# Persistence layer

The backend persistence implementation uses SQLAlchemy 2 and PostgreSQL via
`psycopg`. This is the runtime repository; tests use the same repository and
SQLAlchemy metadata with an isolated in-memory SQLite engine. There is no
test-only in-memory repository in application code.

## Configuration and startup

Set `DATABASE_URL` in the backend process environment or in the ignored
`backend/.env` file. For example:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

No connection is opened and no schema is created during FastAPI startup. When
`DATABASE_URL` is absent, application startup and health checks remain
available; calling `get_repository()` raises
`PersistenceNotConfigured` (`code="persistence_not_configured"`). The API maps missing persistence to HTTP 503.

Install the root package's persistence extra from the repository root:

```bash
python -m pip install -e ".[persistence]"
```

## Schema migration

The initial PostgreSQL schema is
`backend/migrations/001_initial_persistence.sql`. Review and apply it
explicitly to the intended database using a PostgreSQL SQL client, for example:

```bash
PYTHONPATH=src .venv/bin/python -m backend.app.db.migrate
```

Do not run this against a remote database without explicit authorization and
environment confirmation. Application startup never runs migrations.

## Repository contract

`backend.app.repositories.base.Repository` is the storage protocol.
`PostgresRepository` is the runtime implementation and accepts an injected
SQLAlchemy session factory for isolated tests. Persist validated Pydantic agent
results as JSON without recalculating their figures. Monetary values that need
queryable columns use `NUMERIC(18, 2)`; serialized agent JSON retains the shared
schema's decimal-string representation. `is_sample` is explicit on both
profiles and transactions and defaults to false.

`list_budget_revisions(budget_id)` resolves the parent chain and returns the
root plan and its descendants in revision order. Research source metadata is
stored in `research_runs.sources_json` as well as in the complete result JSON.

The migration command accepts `postgres://`, `postgresql://`, and `postgresql+psycopg://` URLs, tracks applied filenames, and applies pending SQL in one transaction. For a database already initialized manually with the original SQL, do not rerun the initial migration; use the existing schema.
