"""Lazy SQLAlchemy engine and session factory construction."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def create_database_engine(database_url: str) -> Engine:
    """Create an engine for the configured database without connecting eagerly."""
    options: dict[str, object] = {"pool_pre_ping": True}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        options.update(
            {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
        )
    if database_url.startswith("postgresql"):
        options.update(pool_size=5, max_overflow=5, pool_recycle=300,
                       connect_args={"connect_timeout": 10, "prepare_threshold": None})
    return create_engine(database_url, **options)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
