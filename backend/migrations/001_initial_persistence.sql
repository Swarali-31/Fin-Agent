-- PostgreSQL schema for FinAgent persistence.
-- Apply explicitly after reviewing the target database; this file is not
-- executed by application startup or the test suite.

CREATE TABLE profiles (
    profile_id VARCHAR(128) PRIMARY KEY,
    currency VARCHAR(3) NOT NULL,
    profile_json JSON NOT NULL,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE transactions (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    transaction_id VARCHAR(128) NOT NULL,
    transaction_date DATE NOT NULL,
    description TEXT NOT NULL,
    merchant TEXT,
    amount NUMERIC(18, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    transaction_type VARCHAR(16) NOT NULL,
    category VARCHAR(32),
    is_recurring BOOLEAN,
    transaction_json JSON NOT NULL,
    is_sample BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_transactions_profile_transaction UNIQUE (profile_id, transaction_id)
);
CREATE INDEX ix_transactions_profile_date ON transactions(profile_id, transaction_date);

CREATE TABLE expense_analyses (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL,
    analysis_version VARCHAR(64),
    currency VARCHAR(3),
    monthly_income NUMERIC(18, 2),
    monthly_expenses NUMERIC(18, 2),
    result_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_expense_analyses_analysis_version ON expense_analyses(analysis_version);
CREATE INDEX ix_expense_analyses_profile_created ON expense_analyses(profile_id, created_at);

CREATE TABLE budgets (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    budget_id VARCHAR(64),
    parent_budget_id VARCHAR(64) REFERENCES budgets(budget_id) ON DELETE SET NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(16) NOT NULL,
    source_analysis_version VARCHAR(64),
    currency VARCHAR(3) NOT NULL,
    monthly_income NUMERIC(18, 2) NOT NULL,
    planned_monthly_savings NUMERIC(18, 2) NOT NULL,
    result_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_budgets_budget_id UNIQUE (budget_id)
);
CREATE INDEX ix_budgets_profile_source ON budgets(profile_id, source_analysis_version);
CREATE INDEX ix_budgets_source_analysis_version ON budgets(source_analysis_version);
CREATE INDEX ix_budgets_parent ON budgets(parent_budget_id);

CREATE TABLE research_runs (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) REFERENCES profiles(profile_id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL,
    question TEXT NOT NULL,
    sources_json JSON NOT NULL,
    result_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_research_runs_profile_created ON research_runs(profile_id, created_at);

CREATE TABLE reports (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    status VARCHAR(16) NOT NULL,
    analysis_version VARCHAR(64),
    source_analysis_version VARCHAR(64),
    report_version VARCHAR(64),
    budget_id VARCHAR(64),
    result_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_reports_analysis_version ON reports(analysis_version);
CREATE INDEX ix_reports_source_analysis_version ON reports(source_analysis_version);
CREATE INDEX ix_reports_report_version ON reports(report_version);
CREATE INDEX ix_reports_profile_created ON reports(profile_id, created_at);

CREATE TABLE workflow_runs (
    id VARCHAR(36) PRIMARY KEY,
    profile_id VARCHAR(128) REFERENCES profiles(profile_id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL,
    input_json JSON NOT NULL,
    result_json JSON,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_workflow_runs_profile_created ON workflow_runs(profile_id, created_at);

CREATE TABLE trace_events (
    id VARCHAR(36) PRIMARY KEY,
    workflow_run_id VARCHAR(36) NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    agent VARCHAR(64),
    payload_json JSON NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_trace_events_workflow_created ON trace_events(workflow_run_id, created_at);
