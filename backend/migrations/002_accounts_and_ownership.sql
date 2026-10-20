-- Accounts use backend-only password hashes and revocable HttpOnly sessions.
-- Existing financial rows are retained as unowned; never assign them to a new user.
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(254) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE auth_sessions (
    token_hash VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX ix_auth_sessions_expiry ON auth_sessions(expires_at);
ALTER TABLE profiles ADD COLUMN user_id VARCHAR(36) REFERENCES users(id);
ALTER TABLE research_runs ADD COLUMN user_id VARCHAR(36) REFERENCES users(id);
ALTER TABLE workflow_runs ADD COLUMN user_id VARCHAR(36) REFERENCES users(id);
CREATE INDEX ix_profiles_user_id ON profiles(user_id);
CREATE INDEX ix_research_runs_user_id ON research_runs(user_id);
CREATE INDEX ix_workflow_runs_user_id ON workflow_runs(user_id);

-- The browser uses FastAPI, never the Supabase Data API. No anonymous access.
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE expense_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE trace_events ENABLE ROW LEVEL SECURITY;
