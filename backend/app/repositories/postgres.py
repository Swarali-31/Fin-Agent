"""PostgreSQL-backed runtime repository."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any
from uuid import uuid4

from finagent.schemas.budget import BudgetPlan
from finagent.schemas.common import AgentStatus
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, Transaction
from finagent.schemas.report import FinancialReport
from finagent.schemas.research import ResearchResult
from pydantic import BaseModel
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria
from sqlalchemy.exc import IntegrityError

from backend.app.config.settings import Settings, get_settings
from backend.app.db.models import (
    BudgetRecord,
    ExpenseAnalysisRecord,
    ProfileRecord,
    ReportRecord,
    ResearchRunRecord,
    TraceEventRecord,
    TransactionRecord,
    WorkflowRunRecord,
)
from backend.app.db.session import create_database_engine, create_session_factory
from backend.app.repositories.base import PersistenceNotConfigured, Repository


def _payload(value: BaseModel) -> dict[str, Any]:
    return value.model_dump(mode="json")


def _status(value: AgentStatus | str) -> str:
    return value.value if isinstance(value, AgentStatus) else str(value)


def _amount(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if not isinstance(value, dict) or value.get("amount") is None:
        return None
    return Decimal(str(value["amount"]))


class PostgresRepository:
    """SQLAlchemy repository intended for PostgreSQL runtime use.

    A session factory can be injected for isolated tests (e.g. SQLite); the
    default factory is built only from configured ``DATABASE_URL``.
    """

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def for_user(self, user_id: str) -> PostgresRepository:
        """Every read, including detail/count queries, is scoped at the ORM boundary."""
        factory = sessionmaker(bind=self._sessions.kw["bind"], expire_on_commit=False)

        @event.listens_for(factory, "do_orm_execute")
        def restrict(execute_state: Any) -> None:
            if not execute_state.is_select:
                return
            owned_profiles = select(ProfileRecord.profile_id).where(ProfileRecord.user_id == user_id)
            owned_workflows = select(WorkflowRunRecord.id).where(WorkflowRunRecord.user_id == user_id)
            statement = execute_state.statement
            for model in (ProfileRecord, ResearchRunRecord, WorkflowRunRecord):
                statement = statement.options(with_loader_criteria(model, model.user_id == user_id))
            for model in (TransactionRecord, ExpenseAnalysisRecord, BudgetRecord, ReportRecord):
                statement = statement.options(with_loader_criteria(model, model.profile_id.in_(owned_profiles)))
            statement = statement.options(with_loader_criteria(TraceEventRecord, TraceEventRecord.workflow_run_id.in_(owned_workflows)))
            execute_state.statement = statement

        @event.listens_for(factory, "before_flush")
        def assign_owner(session: Session, *_args: Any) -> None:
            for record in session.new:
                if isinstance(record, (ProfileRecord, ResearchRunRecord, WorkflowRunRecord)):
                    record.user_id = user_id

        return PostgresRepository(factory)

    def create_profile(self, profile_id: str, currency: str) -> None:
        with self._sessions.begin() as session:
            if session.get(ProfileRecord, profile_id) is not None:
                raise ValueError("Profile already exists.")
            session.add(ProfileRecord(
                profile_id=profile_id, currency=currency,
                profile_json={"profile_id": profile_id, "currency": currency, "transactions": []},
                is_sample=False,
            ))

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._sessions() as session:
            return [{"profile_id": row.profile_id, "currency": row.currency,
                     "is_sample": row.is_sample}
                    for row in session.scalars(select(ProfileRecord).order_by(ProfileRecord.profile_id))]

    def save_profile(self, profile: FinancialProfile, *, is_sample: bool = False) -> str:
        payload = _payload(profile)
        with self._sessions.begin() as session:
            record = session.get(ProfileRecord, profile.profile_id)
            if record is None:
                record = ProfileRecord(
                    profile_id=profile.profile_id,
                    currency=profile.currency,
                    profile_json=payload,
                    is_sample=is_sample,
                )
                session.add(record)
            else:
                record.currency = profile.currency
                record.profile_json = payload
                record.is_sample = is_sample
        return profile.profile_id

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            record = session.get(ProfileRecord, profile_id)
            if record is None:
                return None
            return {
                "profile_id": record.profile_id,
                "currency": record.currency,
                "profile": record.profile_json,
                "is_sample": record.is_sample,
            }

    def save_transactions(
        self,
        profile_id: str,
        transactions: list[Transaction],
        *,
        currency: str,
        is_sample: bool = False,
    ) -> int:
        with self._sessions.begin() as session:
            if session.get(ProfileRecord, profile_id) is None:
                raise ValueError(f"Profile {profile_id!r} must be saved before its transactions.")
            count = 0
            for transaction in transactions:
                payload = _payload(transaction)
                record = session.scalar(
                    select(TransactionRecord).where(
                        TransactionRecord.profile_id == profile_id,
                        TransactionRecord.transaction_id == transaction.id,
                    )
                )
                if record is None:
                    record = TransactionRecord(
                        profile_id=profile_id,
                        transaction_id=transaction.id,
                        transaction_date=transaction.date,
                        description=transaction.description,
                        merchant=transaction.merchant,
                        amount=transaction.amount.amount,
                        currency=currency,
                        transaction_type=transaction.type.value,
                        category=transaction.category.value if transaction.category else None,
                        is_recurring=transaction.is_recurring,
                        transaction_json=payload,
                        is_sample=is_sample,
                    )
                    session.add(record)
                else:
                    record.transaction_date = transaction.date
                    record.description = transaction.description
                    record.merchant = transaction.merchant
                    record.amount = transaction.amount.amount
                    record.currency = currency
                    record.transaction_type = transaction.type.value
                    record.category = transaction.category.value if transaction.category else None
                    record.is_recurring = transaction.is_recurring
                    record.transaction_json = payload
                    record.is_sample = is_sample
                count += 1
        return count

    def get_transactions(self, profile_id: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TransactionRecord)
                .where(TransactionRecord.profile_id == profile_id)
                .order_by(TransactionRecord.transaction_date, TransactionRecord.transaction_id)
            ).all()
            return [
                {
                    "transaction_id": row.transaction_id,
                    "date": row.transaction_date.isoformat(),
                    "amount": str(row.amount.quantize(Decimal("0.01"))),
                    "currency": row.currency,
                    "is_sample": row.is_sample,
                    "transaction": row.transaction_json,
                }
                for row in rows if not row.transaction_json.get("_finagent_deleted", False)
            ]

    def set_transactions_deleted(self, profile_id: str, transaction_ids: list[str], deleted: bool) -> int:
        # Soft deletion keeps an undo path and preserves historical reports.
        with self._sessions.begin() as session:
            rows = session.scalars(select(TransactionRecord).where(
                TransactionRecord.profile_id == profile_id,
                TransactionRecord.transaction_id.in_(transaction_ids),
            )).all()
            if len(rows) != len(set(transaction_ids)):
                raise KeyError("A selected transaction was not found.")
            for row in rows:
                payload = dict(row.transaction_json)
                if deleted:
                    payload["_finagent_deleted"] = True
                else:
                    payload.pop("_finagent_deleted", None)
                row.transaction_json = payload
            return len(rows)

    def save_expense_analysis(
        self,
        profile_id: str,
        result: ExpenseAnalysisResult,
    ) -> str:
        payload = _payload(result)
        summary = payload.get("summary") or {}
        row_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                ExpenseAnalysisRecord(
                    id=row_id,
                    profile_id=profile_id,
                    status=_status(result.status),
                    analysis_version=result.analysis_version,
                    currency=summary.get("currency"),
                    monthly_income=_amount(summary, "monthly_income"),
                    monthly_expenses=_amount(summary, "monthly_expenses"),
                    result_json=payload,
                )
            )
        return row_id

    def save_budget(self, profile_id: str, result: BudgetPlan) -> str:
        payload = _payload(result)
        revision_info = payload.get("revision_info") or {}
        parent_budget_id = revision_info.get("parent_budget_id") or None
        row_id = str(uuid4())
        # Budget IDs describe immutable content. Repeating the same plan reuses
        # its saved record, including when concurrent runs race to insert it.
        with self._sessions() as session:
            existing = session.scalar(select(BudgetRecord).where(BudgetRecord.budget_id == result.budget_id, BudgetRecord.profile_id == profile_id)) if result.budget_id else None
            if existing is not None:
                return existing.id
        try:
            with self._sessions.begin() as session:
                session.add(
                    BudgetRecord(
                        id=row_id,
                        profile_id=profile_id,
                        budget_id=result.budget_id,
                        parent_budget_id=parent_budget_id,
                        revision=result.revision,
                        status=_status(result.status),
                        source_analysis_version=result.source_analysis_version,
                        currency=result.currency,
                        monthly_income=result.monthly_income.amount,
                        planned_monthly_savings=result.planned_monthly_savings.amount,
                        result_json=payload,
                    )
                )
        except IntegrityError:
            with self._sessions() as session:
                existing = session.scalar(select(BudgetRecord).where(BudgetRecord.budget_id == result.budget_id, BudgetRecord.profile_id == profile_id)) if result.budget_id else None
                if existing is None:
                    raise
                return existing.id
        return row_id

    def list_budget_revisions(self, budget_id: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            selected = session.scalar(
                select(BudgetRecord).where(BudgetRecord.budget_id == budget_id)
            )
            if selected is None:
                return []
            root = selected
            while root.parent_budget_id:
                parent = session.scalar(
                    select(BudgetRecord).where(
                        BudgetRecord.budget_id == root.parent_budget_id
                    )
                )
                if parent is None:
                    break
                root = parent

            lineage_ids = {root.budget_id}
            lineage = [root]
            while lineage:
                parent = lineage.pop()
                children = session.scalars(
                    select(BudgetRecord).where(
                        BudgetRecord.parent_budget_id == parent.budget_id
                    )
                ).all()
                for child in children:
                    if child.budget_id not in lineage_ids:
                        lineage_ids.add(child.budget_id)
                        lineage.append(child)

            rows = session.scalars(
                select(BudgetRecord)
                .where(BudgetRecord.budget_id.in_(lineage_ids))
                .order_by(BudgetRecord.revision, BudgetRecord.created_at)
            ).all()
            return [
                {
                    "budget_id": row.budget_id,
                    "parent_budget_id": row.parent_budget_id,
                    "revision": row.revision,
                    "source_analysis_version": row.source_analysis_version,
                    "result": row.result_json,
                }
                for row in rows
            ]

    def save_research_run(
        self,
        result: ResearchResult,
        *,
        profile_id: str | None = None,
    ) -> str:
        payload = _payload(result)
        row_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                ResearchRunRecord(
                    id=row_id,
                    profile_id=profile_id,
                    status=_status(result.status),
                    question=result.question,
                    sources_json=payload.get("sources", []),
                    result_json=payload,
                )
            )
        return row_id

    def save_report(self, profile_id: str, result: FinancialReport) -> str:
        payload = _payload(result)
        source_versions = payload.get("source_versions") or {}
        row_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                ReportRecord(
                    id=row_id,
                    profile_id=profile_id,
                    status=_status(result.status),
                    analysis_version=source_versions.get("analysis_version"),
                    source_analysis_version=source_versions.get("analysis_version"),
                    report_version=result.report_version,
                    budget_id=source_versions.get("budget_id"),
                    result_json=payload,
                )
            )
        return row_id

    def create_workflow_run(
        self,
        *,
        input_data: dict[str, Any],
        started_at: datetime,
        profile_id: str | None = None,
    ) -> str:
        row_id = str(uuid4())
        with self._sessions.begin() as session:
            session.add(
                WorkflowRunRecord(
                    id=row_id,
                    profile_id=profile_id,
                    status="running",
                    input_json=input_data,
                    result_json=None,
                    started_at=started_at,
                )
            )
        return row_id

    def finish_workflow_run(
        self,
        workflow_run_id: str,
        *,
        status: str,
        result_data: dict[str, Any] | None,
        finished_at: datetime,
    ) -> None:
        with self._sessions.begin() as session:
            row = session.get(WorkflowRunRecord, workflow_run_id)
            if row is None:
                raise KeyError(f"Workflow run {workflow_run_id!r} was not found.")
            row.status = status
            row.result_json = result_data
            row.finished_at = finished_at

    def add_trace_event(
        self,
        workflow_run_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        agent: str | None = None,
    ) -> str:
        row_id = str(uuid4())
        with self._sessions.begin() as session:
            if session.get(WorkflowRunRecord, workflow_run_id) is None:
                raise KeyError(f"Workflow run {workflow_run_id!r} was not found.")
            session.add(
                TraceEventRecord(
                    id=row_id,
                    workflow_run_id=workflow_run_id,
                    event_type=event_type,
                    agent=agent,
                    payload_json=payload,
                )
            )
        return row_id

    def list_trace_events(self, workflow_run_id: str) -> list[dict[str, Any]]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TraceEventRecord)
                .where(TraceEventRecord.workflow_run_id == workflow_run_id)
                .order_by(TraceEventRecord.created_at, TraceEventRecord.id)
            ).all()
            return [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "agent": row.agent,
                    "payload": row.payload_json,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def get_workflow_run(self, workflow_run_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.get(WorkflowRunRecord, workflow_run_id)
            if row is None:
                return None
            return {
                "run_id": row.id,
                "status": row.status,
                "input": row.input_json,
                "result": row.result_json,
                "started_at": row.started_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }

    def list_workflow_runs(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._sessions() as session:
            query = select(WorkflowRunRecord)
            count_query = select(func.count()).select_from(WorkflowRunRecord)
            if status is not None:
                query = query.where(WorkflowRunRecord.status == status)
                count_query = count_query.where(WorkflowRunRecord.status == status)
            total = session.scalar(count_query) or 0
            rows = session.scalars(
                query.order_by(WorkflowRunRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._workflow_payload(row) for row in rows], total

    def list_expense_analyses(
        self,
        profile_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._sessions() as session:
            query = select(ExpenseAnalysisRecord).where(
                ExpenseAnalysisRecord.profile_id == profile_id
            )
            total = session.scalar(
                select(func.count()).select_from(ExpenseAnalysisRecord).where(
                    ExpenseAnalysisRecord.profile_id == profile_id
                )
            ) or 0
            rows = session.scalars(
                query.order_by(ExpenseAnalysisRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._analysis_payload(row) for row in rows], total

    def get_expense_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.get(ExpenseAnalysisRecord, analysis_id)
            return self._analysis_payload(row) if row is not None else None

    def get_latest_expense_analysis(self, profile_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.scalar(
                select(ExpenseAnalysisRecord)
                .where(ExpenseAnalysisRecord.profile_id == profile_id)
                .order_by(ExpenseAnalysisRecord.created_at.desc())
                .limit(1)
            )
            return self._analysis_payload(row) if row is not None else None

    def list_budgets(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._sessions() as session:
            query = select(BudgetRecord)
            count_query = select(func.count()).select_from(BudgetRecord)
            if profile_id is not None:
                query = query.where(BudgetRecord.profile_id == profile_id)
                count_query = count_query.where(BudgetRecord.profile_id == profile_id)
            total = session.scalar(count_query) or 0
            rows = session.scalars(
                query.order_by(BudgetRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._budget_payload(row) for row in rows], total

    def get_budget(self, budget_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.scalar(
                select(BudgetRecord).where(
                    (BudgetRecord.budget_id == budget_id)
                    | (BudgetRecord.id == budget_id)
                )
            )
            return self._budget_payload(row) if row is not None else None

    def list_research_runs(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._sessions() as session:
            query = select(ResearchRunRecord)
            count_query = select(func.count()).select_from(ResearchRunRecord)
            if profile_id is not None:
                query = query.where(ResearchRunRecord.profile_id == profile_id)
                count_query = count_query.where(ResearchRunRecord.profile_id == profile_id)
            total = session.scalar(count_query) or 0
            rows = session.scalars(
                query.order_by(ResearchRunRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._research_payload(row) for row in rows], total

    def get_research_run(self, research_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.get(ResearchRunRecord, research_id)
            return self._research_payload(row) if row is not None else None

    def list_reports(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        with self._sessions() as session:
            query = select(ReportRecord)
            count_query = select(func.count()).select_from(ReportRecord)
            if profile_id is not None:
                query = query.where(ReportRecord.profile_id == profile_id)
                count_query = count_query.where(ReportRecord.profile_id == profile_id)
            total = session.scalar(count_query) or 0
            rows = session.scalars(
                query.order_by(ReportRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            return [self._report_payload(row) for row in rows], total

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            row = session.get(ReportRecord, report_id)
            return self._report_payload(row) if row is not None else None

    @staticmethod
    def _analysis_payload(row: ExpenseAnalysisRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "profile_id": row.profile_id,
            "status": row.status,
            "analysis_version": row.analysis_version,
            "created_at": row.created_at.isoformat(),
            "result": row.result_json,
        }

    @staticmethod
    def _budget_payload(row: BudgetRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "budget_id": row.budget_id,
            "parent_budget_id": row.parent_budget_id,
            "revision": row.revision,
            "profile_id": row.profile_id,
            "status": row.status,
            "source_analysis_version": row.source_analysis_version,
            "created_at": row.created_at.isoformat(),
            "result": row.result_json,
        }

    @staticmethod
    def _research_payload(row: ResearchRunRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "profile_id": row.profile_id,
            "status": row.status,
            "question": row.question,
            "created_at": row.created_at.isoformat(),
            "sources": row.sources_json,
            "result": row.result_json,
        }

    @staticmethod
    def _report_payload(row: ReportRecord) -> dict[str, Any]:
        return {
            "id": row.id,
            "profile_id": row.profile_id,
            "status": row.status,
            "analysis_version": row.analysis_version,
            "report_version": row.report_version,
            "budget_id": row.budget_id,
            "created_at": row.created_at.isoformat(),
            "result": row.result_json,
        }

    @staticmethod
    def _workflow_payload(row: WorkflowRunRecord) -> dict[str, Any]:
        return {
            "run_id": row.id,
            "status": row.status,
            "input": row.input_json,
            "result": row.result_json,
            "started_at": row.started_at.isoformat(),
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }


@lru_cache(maxsize=4)
def _postgres_repository_for_url(database_url: str) -> PostgresRepository:
    engine = create_database_engine(database_url)
    return PostgresRepository(create_session_factory(engine))


def get_repository(settings: Settings | None = None) -> Repository:
    """Return the configured PostgreSQL repository or a typed setup error."""
    config = settings or get_settings()
    database_url = (config.database_url or "").strip()
    if not database_url:
        raise PersistenceNotConfigured()
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url.removeprefix("postgresql://")
    if not database_url.startswith(("postgresql+psycopg://", "sqlite:///")):
        raise ValueError("DATABASE_URL must use PostgreSQL or a persistent sqlite:/// file.")
    return _postgres_repository_for_url(database_url)
