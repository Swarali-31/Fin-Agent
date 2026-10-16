"""Application services used by the versioned HTTP API."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from finagent.sample_data import sample_profile
from finagent.agents.expense_analysis.calculations import compute_expense_metrics
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


def stored_profile(repository: Repository, profile_id: str) -> dict[str, Any]:
    record = repository.get_profile(profile_id)
    if record is None:
        raise APIServiceError(404, "profile_not_found", "Profile was not found.")
    profile = dict(record["profile"])
    profile["transactions"] = [row["transaction"] for row in repository.get_transactions(profile_id)]
    return profile


def profile_version(profile: dict[str, Any]) -> str:
    return compute_expense_metrics(FinancialProfile.model_validate(profile)).analysis_version


def current_analysis(repository: Repository, profile_id: str) -> dict[str, Any]:
    profile = stored_profile(repository, profile_id)
    if not profile["transactions"]:
        raise APIServiceError(422, "missing_transactions", "Add transactions before analysis.")
    latest = repository.get_latest_expense_analysis(profile_id)
    if not latest:
        raise APIServiceError(409, "missing_analysis", "Run Expense Analysis first.")
    result = latest["result"]
    if result.get("status") == "failed" or result.get("analysis_version") != profile_version(profile):
        raise APIServiceError(409, "stale_analysis", "Transactions changed; run Expense Analysis again.")
    return result


class _BoundWorkflowRepository:
    """Route orchestrator persistence into the already-created API run."""

    def __init__(self, repository: Repository, run_id: str, profile: dict[str, Any] | None = None) -> None:
        self.repository = repository
        self.run_id = run_id
        self.profile = profile

    def create_workflow_run(self, **_kwargs: Any) -> str:
        _ = _kwargs
        return self.run_id

    def add_trace_event(self, _workflow_run_id: str, **kwargs: Any) -> str:
        _ = _workflow_run_id
        return self.repository.add_trace_event(self.run_id, **kwargs)

    def finish_workflow_run(self, _workflow_run_id: str, **kwargs: Any) -> None:
        _ = _workflow_run_id
        data = kwargs.get("result_data") or {}
        profile_id = self.profile.get("profile_id") if self.profile else None
        if profile_id and self.profile.get("transactions"):
            if profile_version(stored_profile(self.repository, profile_id)) != profile_version(self.profile):
                data.update(status="failed", final_answer="Transactions changed during execution; run the workflow again.")
                data.setdefault("errors", []).append({"code": "stale_analysis", "message": data["final_answer"]})
                kwargs["status"] = "failed"
                self.repository.finish_workflow_run(self.run_id, **kwargs)
                return
        for step in (data.get("plan") or {}).get("steps", []):
            envelope = data.get("results", {}).get(step["id"], {})
            if step.get("status") not in {"success", "partial"} or envelope.get("status") == "failed":
                continue
            result = envelope.get("result") or {}
            agent = step["agent"]
            if agent == "expense_analysis" and profile_id:
                self.repository.save_expense_analysis(profile_id, ExpenseAnalysisResult.model_validate(result))
            elif agent == "budget_planning" and profile_id:
                self.repository.save_budget(profile_id, BudgetPlan.model_validate(result))
            elif agent == "financial_report" and profile_id and result.get("validation_status") != "rejected":
                self.repository.save_report(profile_id, FinancialReport.model_validate(result))
            elif agent == "financial_research":
                self.repository.save_research_run(ResearchResult.model_validate(result), profile_id=profile_id)
        self.repository.finish_workflow_run(self.run_id, **kwargs)


def configured_repository(
    settings: Settings | None = None,
    request: Request | None = None,
) -> Repository:
    injected = getattr(request.app.state, "repository", None) if request else None
    if injected is not None:
        user = getattr(request.state, "user", None) if request else None
        return injected.for_user(user["id"]) if user else injected
    try:
        repository = get_repository(settings=settings or get_settings())
        user = getattr(request.state, "user", None) if request else None
        return repository.for_user(user["id"]) if user else repository
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
    repo = optional_repository(request=request)
    if agent == "expense_analysis" and isinstance(payload, dict) and payload.get("profile_id"):
        repo = configured_repository(request=request)
        payload = {"profile": stored_profile(repo, payload["profile_id"])}
    if profile_id and agent in {"budget_planning", "financial_report"}:
        repo = configured_repository(request=request)
        latest = current_analysis(repo, profile_id)
        if not isinstance(payload, dict):
            raise APIServiceError(422, "invalid_input", "Agent input must be an object.")
        payload = dict(payload)
        analysis_key = "new_analysis" if revise else "expense_analysis"
        supplied = payload.get(analysis_key)
        if supplied and (not isinstance(supplied, dict) or supplied.get("analysis_version") != latest["analysis_version"]):
            raise APIServiceError(409, "stale_analysis", "Use the latest stored expense analysis.")
        payload[analysis_key] = latest
        if revise and payload.get("previous"):
            previous_id = payload["previous"].get("budget_id")
            saved_previous = repo.get_budget(previous_id) if previous_id else None
            if not saved_previous or saved_previous.get("profile_id") != profile_id:
                raise APIServiceError(404, "budget_not_found", "Choose a saved budget from this financial profile.")
            payload["previous"] = saved_previous["result"]
        if agent == "financial_report":
            budgets, _ = repo.list_budgets(profile_id=profile_id, limit=1, offset=0)
            if not budgets:
                raise APIServiceError(409, "missing_budget", "Create a budget first.")
            budget = budgets[0]["result"]
            if budget.get("source_analysis_version") != latest["analysis_version"]:
                raise APIServiceError(409, "stale_budget", "Revise the budget using the latest analysis.")
            if payload.get("budget") and payload["budget"].get("budget_id") != budget.get("budget_id"):
                raise APIServiceError(409, "stale_budget", "Use the latest stored budget.")
            payload["budget"] = budget
            if "research" not in payload:
                research, _ = repo.list_research_runs(profile_id=profile_id, limit=1, offset=0)
                payload["research"] = research[0]["result"] if research else None
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
        if "savings_goal" in payload or "essential_categories" in payload:
            context = {**(context or {}), "budget_preferences": {key: payload[key] for key in ("savings_goal", "essential_categories") if key in payload}}
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
    if profile_id and agent in {"budget_planning", "financial_report"}:
        refreshed = current_analysis(configured_repository(request=request), profile_id)
        if refreshed["analysis_version"] != latest["analysis_version"]:
            raise APIServiceError(409, "stale_analysis", "Analysis changed during execution; try again.")
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
    if repository.get_profile(profile_id) is not None:
        raise APIServiceError(409, "profile_exists", "Load sample data into a new profile only.")
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
    profile = stored_profile(repository, profile_id)
    # A dashboard read must not trigger model calls or create duplicate analyses.
    result = compute_expense_metrics(FinancialProfile.model_validate(profile))
    return result.summary.model_dump(mode="json")


async def start_workflow(request: Request, task: str, context: dict[str, Any]) -> str:
    repository = configured_repository(request=request)
    context = dict(context)
    supplied_profile = context.get("profile") or {}
    if not isinstance(supplied_profile, dict):
        raise APIServiceError(422, "invalid_input", "Profile context must be an object.")
    profile_id = context.get("profile_id") or supplied_profile.get("profile_id")
    if profile_id is not None and not isinstance(profile_id, str):
        raise APIServiceError(422, "invalid_input", "Profile ID must be a string.")
    context.pop("cached_expense_analysis", None)
    if profile_id:
        context["profile_id"] = profile_id
        context["profile"] = stored_profile(repository, profile_id)
        # Persisted data is authoritative; browser-provided upstream snapshots are not.
        for key in ("transactions", "expense_analysis", "budget", "research"):
            context.pop(key, None)
        if context["profile"].get("transactions"):
            latest = repository.get_latest_expense_analysis(profile_id)
            if latest and latest["result"].get("status") == "success" and latest["result"].get("analysis_version") == profile_version(context["profile"]):
                context["cached_expense_analysis"] = latest["result"]
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
        workflow_result = await run_workflow(
            task,
            workflow_context,
            llm=injected.get("llm"),
            adapters=adapter_registry(request),
            repository=_BoundWorkflowRepository(repository, run_id, context.get("profile")),  # type: ignore[arg-type]
        )
        saved = repository.get_workflow_run(run_id)
        if saved and saved["status"] == "running":
            data = workflow_result.model_dump(mode="json")
            data["status"] = "failed"
            data.setdefault("errors", []).append({"code": "persistence_error", "message": "Workflow results could not be saved."})
            repository.finish_workflow_run(run_id, status="failed", result_data=data, finished_at=datetime.now(UTC))
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
