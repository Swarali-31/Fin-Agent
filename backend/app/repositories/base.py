"""Persistence boundary shared by backend services."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from finagent.schemas.budget import BudgetPlan
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile
from finagent.schemas.report import FinancialReport
from finagent.schemas.research import ResearchResult


class PersistenceNotConfigured(RuntimeError):
    """Raised when a persistence operation is requested without DATABASE_URL."""

    code = "persistence_not_configured"

    def __init__(self) -> None:
        super().__init__(
            "Persistence is not configured. Set DATABASE_URL to enable database operations."
        )


@runtime_checkable
class Repository(Protocol):
    """Storage contract; agent computation remains outside this layer."""

    def create_profile(self, profile_id: str, currency: str) -> None: ...

    def list_profiles(self) -> list[dict[str, Any]]: ...

    def save_profile(self, profile: FinancialProfile, *, is_sample: bool = False) -> str: ...

    def get_profile(self, profile_id: str) -> dict[str, Any] | None: ...

    def save_transactions(
        self,
        profile_id: str,
        transactions: list[Any],
        *,
        currency: str,
        is_sample: bool = False,
        import_metadata: dict[str, Any] | None = None,
    ) -> int: ...

    def set_transactions_deleted(self, profile_id: str, transaction_ids: list[str], deleted: bool) -> int: ...

    def get_transactions(self, profile_id: str) -> list[dict[str, Any]]: ...

    def save_expense_analysis(
        self,
        profile_id: str,
        result: ExpenseAnalysisResult,
    ) -> str: ...

    def save_budget(self, profile_id: str, result: BudgetPlan) -> str: ...

    def list_budget_revisions(self, budget_id: str) -> list[dict[str, Any]]: ...

    def save_research_run(
        self,
        result: ResearchResult,
        *,
        profile_id: str | None = None,
    ) -> str: ...

    def save_report(self, profile_id: str, result: FinancialReport) -> str: ...

    def create_workflow_run(
        self,
        *,
        input_data: dict[str, Any],
        started_at: datetime,
        profile_id: str | None = None,
    ) -> str: ...

    def finish_workflow_run(
        self,
        workflow_run_id: str,
        *,
        status: str,
        result_data: dict[str, Any] | None,
        finished_at: datetime,
    ) -> None: ...

    def add_trace_event(
        self,
        workflow_run_id: str,
        *,
        event_type: str,
        payload: dict[str, Any],
        agent: str | None = None,
    ) -> str: ...

    def list_trace_events(self, workflow_run_id: str) -> list[dict[str, Any]]: ...

    def get_workflow_run(self, workflow_run_id: str) -> dict[str, Any] | None: ...

    def list_workflow_runs(
        self,
        *,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def list_expense_analyses(
        self,
        profile_id: str,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_expense_analysis(self, analysis_id: str) -> dict[str, Any] | None: ...

    def get_latest_expense_analysis(self, profile_id: str) -> dict[str, Any] | None: ...

    def list_budgets(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_budget(self, budget_id: str) -> dict[str, Any] | None: ...

    def list_research_runs(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_research_run(self, research_id: str) -> dict[str, Any] | None: ...

    def list_reports(
        self,
        *,
        limit: int,
        offset: int,
        profile_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]: ...

    def get_report(self, report_id: str) -> dict[str, Any] | None: ...
