"""SQLAlchemy persistence models for backend-owned records."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for backend persistence models."""

    type_annotation_map = {dict[str, Any]: JSON}


class ProfileRecord(Base):
    __tablename__ = "profiles"

    profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    transactions: Mapped[list[TransactionRecord]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class TransactionRecord(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("profile_id", "transaction_id", name="uq_transactions_profile_transaction"),
        Index("ix_transactions_profile_date", "profile_id", "transaction_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("profiles.profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    transaction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(32))
    is_recurring: Mapped[bool | None] = mapped_column(Boolean)
    transaction_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    profile: Mapped[ProfileRecord] = relationship(back_populates="transactions")


class ExpenseAnalysisRecord(Base):
    __tablename__ = "expense_analyses"
    __table_args__ = (Index("ix_expense_analyses_profile_created", "profile_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.profile_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    analysis_version: Mapped[str | None] = mapped_column(String(64), index=True)
    currency: Mapped[str | None] = mapped_column(String(3))
    monthly_income: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    monthly_expenses: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class BudgetRecord(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("budget_id", name="uq_budgets_budget_id"),
        Index("ix_budgets_profile_source", "profile_id", "source_analysis_version"),
        Index("ix_budgets_parent", "parent_budget_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.profile_id", ondelete="CASCADE"), nullable=False)
    budget_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_budget_id: Mapped[str | None] = mapped_column(
        ForeignKey("budgets.budget_id", ondelete="SET NULL"),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_analysis_version: Mapped[str | None] = mapped_column(String(64), index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    monthly_income: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    planned_monthly_savings: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ResearchRunRecord(Base):
    __tablename__ = "research_runs"
    __table_args__ = (Index("ix_research_runs_profile_created", "profile_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.profile_id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class ReportRecord(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_profile_created", "profile_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("profiles.profile_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    analysis_version: Mapped[str | None] = mapped_column(String(64), index=True)
    source_analysis_version: Mapped[str | None] = mapped_column(String(64), index=True)
    report_version: Mapped[str | None] = mapped_column(String(64), index=True)
    budget_id: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class WorkflowRunRecord(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_profile_created", "profile_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey("profiles.profile_id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class TraceEventRecord(Base):
    __tablename__ = "trace_events"
    __table_args__ = (Index("ix_trace_events_workflow_created", "workflow_run_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workflow_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    agent: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
