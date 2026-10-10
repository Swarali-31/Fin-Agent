"""Apply versioned SQL migrations transactionally; never run at app startup."""
from pathlib import Path

from sqlalchemy.engine import make_url
import psycopg

from backend.app.config.settings import get_settings


def main() -> None:
    url = get_settings().database_url
    if not url:
        raise SystemExit("Set DATABASE_URL before applying migrations.")
    url = url.replace("postgres://", "postgresql://", 1)
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise SystemExit("Migrations require PostgreSQL.")
    dsn = parsed.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(718234901)")
        connection.execute("CREATE TABLE IF NOT EXISTS finagent_schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())")
        applied = {row[0] for row in connection.execute("SELECT version FROM finagent_schema_migrations")}
        for path in sorted((Path(__file__).resolve().parents[2] / "migrations").glob("*.sql")):
            if path.name in applied:
                continue
            connection.execute(path.read_text(), prepare=False)
            connection.execute("INSERT INTO finagent_schema_migrations(version) VALUES (%s)", (path.name,))
            print(f"Applied {path.name}")
    print("Database migrations are current.")


if __name__ == "__main__":
    main()
