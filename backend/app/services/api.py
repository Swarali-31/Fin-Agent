"""Application services used by the versioned HTTP API."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from finagent.sample_data import sample_profile
from finagent.schemas.budget import BudgetPlan
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.financial import FinancialProfile, Transaction
from finagent.schemas.report import FinancialReport
from finagent.schemas.research import ResearchResult
from pydantic import ValidationError

from backend.app.config.settings import Settings, get_settings
from backend.app.orchestrator.graph import run_workflow
from backend.app.repositories import PersistenceNotConfigured, Repository, get_repository
from backend.app.schemas.common import AgentEnvelope
from backend.app.services.adapters import (
    BudgetPlanningAdapter,
    ExpenseAnalysisAdapter,
    FinancialReportAdapter,
    FinancialResearchAdapter,
)


class APIServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details


class _BoundWorkflowRepository:
    """Route orchestrator persistence into the already-created API run."""

    def __init__(self, repository: Repository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id

    def create_workflow_run(self, **_kwargs: Any) -> str:
        _ = _kwargs
        return self.run_id

    def add_trace_event(self, _workflow_run_id: str, **kwargs: Any) -> str:
        _ = _workflow_run_id
        return self.repository.add_trace_event(self.run_id, **kwargs)

    def finish_workflow_run(self, _workflow_run_id: str, **kwargs: Any) -> None:
        _ = _workflow_run_id
        self.repository.finish_workflow_run(self.run_id, **kwargs)


def configured_repository(
    settings: Settings | None = None,
    request: Request | None = None,
) -> Repository:
    injected = getattr(request.app.state, "repository", None) if request else None
    if injected is not None:
        return injected
    try:
        return get_repository(settings=settings or get_settings())
    except PersistenceNotConfigured:
        raise
    except ValueError as exc:
        raise APIServiceError(
            503,
            "persistence_misconfigured",
            str(exc),
        ) from exc


def optional_repository(
    settings: Settings | None = None,
    request: Request | None = None,
) -> Repository | None:
    try:
        return configured_repository(settings, request)
    except PersistenceNotConfigured:
        return None


def adapter_registry(request: Request) -> dict[str, Any]:
    registry = getattr(request.app.state, "adapters", None)
    if registry is not None:
        return registry
    settings = get_settings()
    return {
        "expense_analysis": ExpenseAnalysisAdapter(settings),
        "budget_planning": BudgetPlanningAdapter(settings),
        "financial_research": FinancialResearchAdapter(settings),
        "financial_report": FinancialReportAdapter(settings),
    }


def injected_context(request: Request) -> dict[str, Any]:
    return dict(getattr(request.app.state, "agent_context", {}) or {})


async def run_specialist(
    request: Request,
    agent: str,
    payload: Any,
    *,
    profile_id: str | None = None,
    revise: bool = False,
) -> AgentEnvelope:
    registry = adapter_registry(request)
    adapter = registry[agent]
    context = injected_context(request)
    if revise:
        if not isinstance(payload, dict):
            raise APIServiceError(
                422,
                "invalid_revision_request",
                "Revision body must contain previous and new_analysis objects.",
            )
        envelope = await adapter.revise(
            payload.get("previous"),
            payload.get("new_analysis"),
            context,
        )
    else:
        envelope = await adapter.run(payload, context)

    if envelope.status == "failed":
        _raise_agent_failure(envelope)

    result = envelope.result or {}
    if agent == "financial_report" and result.get("validation_status") == "rejected":
        raise APIServiceError(
            409,
            "report_inputs_rejected",
            str(result.get("validation_summary", "Report inputs were rejected.")),
            {"validation_issues": result.get("validation_issues", [])},
        )
    if profile_id and agent in {"budget_planning", "financial_report", "financial_research"}:
        repo = optional_repository(request=request)
        if repo is not None and repo.get_profile(profile_id) is None:
            raise APIServiceError(404, "profile_not_found", "Profile was not found.")

    repo = optional_repository(request=request)
    if repo is None:
        return envelope
    if agent == "expense_analysis":
        profile = FinancialProfile.model_validate(payload.get("profile", {}))
        existing_profile = repo.get_profile(profile.profile_id)
        is_sample = bool(existing_profile and existing_profile.get("is_sample"))
        repo.save_profile(profile, is_sample=is_sample)
        repo.save_transactions(
            profile.profile_id,
            profile.transactions,
            currency=profile.currency,
            is_sample=is_sample,
        )
        analysis = ExpenseAnalysisResult.model_validate(result)
        if analysis.status.value != "failed":
            repo.save_expense_analysis(profile.profile_id, analysis)
    elif agent == "budget_planning" and profile_id:
        repo.save_budget(profile_id, BudgetPlan.model_validate(result))
    elif agent == "financial_research":
        repo.save_research_run(
            ResearchResult.model_validate(result),
            profile_id=profile_id,
        )
    elif agent == "financial_report" and profile_id:
        report = FinancialReport.model_validate(result)
        repo.save_report(profile_id, report)
    return envelope


async def accept_transactions(
    profile_id: str,
    body: Any,
    content_type: str,
    repository: Repository,
) -> dict[str, Any]:
    profile_record = repository.get_profile(profile_id)
    if profile_record is None:
        raise APIServiceError(404, "profile_not_found", "Profile was not found.")

    if "text/csv" in content_type:
        raw_rows = _parse_csv(body)
        currency = profile_record["currency"]
    else:
        values = body.get("transactions") if isinstance(body, dict) else body
        if not isinstance(values, list):
            raise APIServiceError(
                422,
                "invalid_transactions",
                "JSON body must be a list or an object containing transactions.",
            )
        raw_rows = values
        currency = profile_record["currency"]

    valid: list[Transaction] = []
    errors: list[dict[str, Any]] = []
    existing_ids = {
        row["transaction_id"] for row in repository.get_transactions(profile_id)
    }
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_rows, start=1):
        try:
            transaction = Transaction.model_validate(_normalize_transaction(raw))
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append(_row_error(index, exc))
            continue
        if transaction.id in existing_ids or transaction.id in seen_ids:
            errors.append(
                {
                    "row": index,
                    "code": "duplicate_transaction_id",
                    "message": f"Transaction id {transaction.id!r} already exists.",
                }
            )
            continue
        seen_ids.add(transaction.id)
        valid.append(transaction)
    if errors:
        conflict_only = all(
            error.get("code") == "duplicate_transaction_id"
            for error in errors
        )
        raise APIServiceError(
            409 if conflict_only else 422,
            "transaction_conflict" if conflict_only else "transaction_rows_invalid",
            (
                "No transactions were saved because one or more IDs already exist."
                if conflict_only
                else "No transactions were saved because one or more rows are invalid."
            ),
            {"row_errors": errors},
        )

    count = repository.save_transactions(
        profile_id,
        valid,
        currency=currency,
    )
    return {"profile_id": profile_id, "inserted": count, "is_sample": False}


def create_sample_profile(profile_id: str, repository: Repository) -> dict[str, Any]:
    profile = sample_profile().model_copy(update={"profile_id": profile_id})
    repository.save_profile(profile, is_sample=True)
    count = repository.save_transactions(
        profile_id,
        profile.transactions,
        currency=profile.currency,
        is_sample=True,
    )
    return {
        "profile_id": profile_id,
        "currency": profile.currency,
        "transactions_inserted": count,
        "is_sample": True,
    }


async def get_profile_summary(
    profile_id: str,
    request: Request,
    repository: Repository,
) -> dict[str, Any]:
    profile_record = repository.get_profile(profile_id)
    if profile_record is None:
        raise APIServiceError(404, "profile_not_found", "Profile was not found.")
    transactions = repository.get_transactions(profile_id)
    if not transactions:
        raise APIServiceError(
            422,
            "missing_transactions",
            "At least one transaction is required to calculate a summary.",
        )
    profile = {
        "profile_id": profile_id,
        "currency": profile_record["currency"],
        "transactions": [row["transaction"] for row in transactions],
    }
    envelope = await adapter_registry(request)["expense_analysis"].run(
        {"profile": profile},
        injected_context(request),
    )
    if envelope.status == "failed":
        _raise_agent_failure(envelope)
    result = ExpenseAnalysisResult.model_validate(envelope.result or {})
    if result.status.value != "failed":
        repository.save_expense_analysis(profile_id, result)
    return result.summary.model_dump(mode="json") if result.summary else {}


async def start_workflow(request: Request, task: str, context: dict[str, Any]) -> str:
    repository = configured_repository(request=request)
    profile_id = context.get("profile_id")
    if profile_id and repository.get_profile(profile_id) is None:
        raise APIServiceError(404, "profile_not_found", "Profile was not found.")
    run_id = repository.create_workflow_run(
        input_data={"task": task, "context": context},
        started_at=datetime.now(UTC),
        profile_id=profile_id,
    )
    task_handle = asyncio.create_task(
        execute_workflow_background(
            request,
            run_id,
            task,
            context,
            repository,
        )
    )
    request.app.state.workflow_tasks[run_id] = task_handle
    return run_id


async def execute_workflow_background(
    request: Request,
    run_id: str,
    task: str,
    context: dict[str, Any],
    repository: Repository,
) -> None:
    try:
        workflow_context = dict(context)
        injected = injected_context(request)
        if "search_provider" in injected:
            workflow_context["search_provider"] = injected["search_provider"]
        await run_workflow(
            task,
            workflow_context,
            llm=injected.get("llm"),
            adapters=adapter_registry(request),
            repository=_BoundWorkflowRepository(repository, run_id),  # type: ignore[arg-type]
        )
    except Exception as exc:
        try:
            repository.finish_workflow_run(
                run_id,
                status="failed",
                result_data={
                    "status": "failed",
                    "errors": [
                        {
                            "code": "workflow_execution_error",
                            "message": "Workflow execution failed.",
                            "details": {"exception_type": type(exc).__name__},
                        }
                    ],
                },
                finished_at=datetime.now(UTC),
            )
        finally:
            request.app.state.workflow_tasks.pop(run_id, None)
    else:
        request.app.state.workflow_tasks.pop(run_id, None)


def _parse_csv(body: Any) -> list[dict[str, Any]]:
    try:
        text = body.decode("utf-8-sig") if isinstance(body, bytes) else str(body)
        reader = csv.DictReader(io.StringIO(text))
        required = {"id", "date", "description", "amount", "type"}
        fields = set(reader.fieldnames or ())
        missing = sorted(required - fields)
        if missing:
            raise APIServiceError(
                422,
                "invalid_csv_header",
                "CSV is missing required columns.",
                {"missing_columns": missing},
            )
        return [dict(row) for row in reader]
    except UnicodeDecodeError as exc:
        raise APIServiceError(
            422,
            "invalid_csv_encoding",
            "CSV must be UTF-8 encoded.",
        ) from exc


def _normalize_transaction(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    if isinstance(normalized.get("amount"), str):
        normalized["amount"] = {"amount": normalized["amount"]}
    if "transaction_id" in normalized and "id" not in normalized:
        normalized["id"] = normalized.pop("transaction_id")
    if "transaction_type" in normalized and "type" not in normalized:
        normalized["type"] = normalized.pop("transaction_type")
    for optional_field in ("merchant", "category", "is_recurring"):
        if normalized.get(optional_field) == "":
            normalized[optional_field] = None
    return normalized


def _row_error(row: int, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        issues = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return {"row": row, "code": "invalid_transaction", "errors": issues}
    return {
        "row": row,
        "code": "invalid_transaction",
        "message": str(exc),
    }


def _raise_agent_failure(envelope: AgentEnvelope) -> None:
    first_error = envelope.errors[0] if envelope.errors else {}
    code = str(first_error.get("code", "agent_failed"))
    if code in {"invalid_input", "validation_error"}:
        status_code = 422
    elif code in {"misconfigured", "search_not_configured"}:
        status_code = 503
    elif code in {"stale_budget", "stale_analysis", "stale_version"}:
        status_code = 409
    else:
        status_code = 422
    raise APIServiceError(
        status_code,
        code,
        str(first_error.get("message", "The specialist could not complete the request.")),
        first_error.get("details") if isinstance(first_error.get("details"), dict) else None,
    )
