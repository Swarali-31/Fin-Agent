"""Thin FastAPI route declarations for the v1 API."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from backend.app.api.responses import success
from backend.app.services import api as services

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health(request: Request) -> Any:
    return success(request, {"status": "ok"})


@router.get("/agents")
async def agents(request: Request) -> Any:
    registry = services.adapter_registry(request)
    return success(
        request,
        {
            name: {
                "capabilities": adapter.capabilities(),
                "integration_status": adapter.status().model_dump(mode="json"),
            }
            for name, adapter in registry.items()
        },
    )


@router.post("/agents/expense-analysis/run")
async def run_expense_analysis(request: Request) -> Any:
    payload = await _json_body(request)
    envelope = await services.run_specialist(request, "expense_analysis", payload)
    return success(request, envelope.model_dump(mode="json"))


@router.post("/agents/budget-planning/run")
async def run_budget_planning(
    request: Request,
    profile_id: str | None = None,
) -> Any:
    payload = await _json_body(request)
    envelope = await services.run_specialist(
        request,
        "budget_planning",
        payload,
        profile_id=profile_id,
    )
    return success(request, envelope.model_dump(mode="json"))


@router.post("/agents/budget-planning/revise")
async def revise_budget(request: Request, profile_id: str | None = None) -> Any:
    payload = await _json_body(request)
    envelope = await services.run_specialist(
        request,
        "budget_planning",
        payload,
        profile_id=profile_id,
        revise=True,
    )
    return success(request, envelope.model_dump(mode="json"))


@router.post("/agents/financial-research/run")
async def run_financial_research(request: Request) -> Any:
    envelope = await services.run_specialist(
        request,
        "financial_research",
        await _json_body(request),
    )
    return success(request, envelope.model_dump(mode="json"))


@router.post("/agents/financial-report/run")
async def run_financial_report(
    request: Request,
    profile_id: str | None = None,
) -> Any:
    envelope = await services.run_specialist(
        request,
        "financial_report",
        await _json_body(request),
        profile_id=profile_id,
    )
    return success(request, envelope.model_dump(mode="json"))


@router.post("/workflows", status_code=202)
async def create_workflow(request: Request) -> Any:
    payload = await _json_body(request)
    if not isinstance(payload, dict) or not isinstance(payload.get("task"), str):
        raise services.APIServiceError(
            422,
            "invalid_workflow_request",
            "Workflow body requires a string task.",
        )
    context = payload.get("context", {})
    if not isinstance(context, dict):
        raise services.APIServiceError(
            422,
            "invalid_workflow_request",
            "Workflow context must be an object.",
        )
    run_id = await services.start_workflow(request, payload["task"], context)
    return success(request, {"run_id": run_id}, status_code=202)


@router.get("/workflows")
async def list_workflows(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
) -> Any:
    repository = services.configured_repository(request=request)
    items, total = repository.list_workflow_runs(
        limit=page_size,
        offset=(page - 1) * page_size,
        status=status,
    )
    return success(request, _page_data(items, total, page, page_size))


@router.get("/workflows/{run_id}")
async def get_workflow(request: Request, run_id: str) -> Any:
    repository = services.configured_repository(request=request)
    result = repository.get_workflow_run(run_id)
    if result is None:
        raise services.APIServiceError(404, "workflow_not_found", "Workflow run was not found.")
    return success(request, result)


@router.get("/workflows/{run_id}/trace")
async def get_workflow_trace(request: Request, run_id: str) -> Any:
    repository = services.configured_repository(request=request)
    if repository.get_workflow_run(run_id) is None:
        raise services.APIServiceError(404, "workflow_not_found", "Workflow run was not found.")
    return success(request, repository.list_trace_events(run_id))


@router.post("/profiles/{profile_id}/transactions")
async def add_transactions(request: Request, profile_id: str) -> Any:
    repository = services.configured_repository(request=request)
    content_type = request.headers.get("content-type", "").lower()
    body = await request.body()
    if "application/json" in content_type:
        try:
            body = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise services.APIServiceError(
                422,
                "invalid_json",
                "Request body is not valid JSON.",
            ) from exc
    result = await services.accept_transactions(
        profile_id,
        body,
        content_type,
        repository,
    )
    return success(request, result)


@router.post("/profiles/{profile_id}/sample-data")
async def add_sample_data(request: Request, profile_id: str) -> Any:
    result = services.create_sample_profile(
        profile_id,
        services.configured_repository(request=request),
    )
    return success(request, result)


@router.get("/profiles/{profile_id}/summary")
async def profile_summary(request: Request, profile_id: str) -> Any:
    repository = services.configured_repository(request=request)
    result = await services.get_profile_summary(profile_id, request, repository)
    return success(request, result)


@router.get("/profiles/{profile_id}/expense-analyses/latest")
async def latest_expense_analysis(request: Request, profile_id: str) -> Any:
    repository = services.configured_repository(request=request)
    if repository.get_profile(profile_id) is None:
        raise services.APIServiceError(404, "profile_not_found", "Profile was not found.")
    result = repository.get_latest_expense_analysis(profile_id)
    if result is None:
        raise services.APIServiceError(
            404,
            "analysis_not_found",
            "No expense analysis exists for this profile.",
        )
    return success(request, result)


@router.get("/profiles/{profile_id}/expense-analyses")
async def list_expense_analyses(
    request: Request,
    profile_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Any:
    repository = services.configured_repository(request=request)
    if repository.get_profile(profile_id) is None:
        raise services.APIServiceError(404, "profile_not_found", "Profile was not found.")
    items, total = repository.list_expense_analyses(
        profile_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success(request, _page_data(items, total, page, page_size))


@router.get("/budgets")
async def list_budgets(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    profile_id: str | None = None,
) -> Any:
    items, total = services.configured_repository(request=request).list_budgets(
        profile_id=profile_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success(request, _page_data(items, total, page, page_size))


@router.get("/budgets/{budget_id}")
async def get_budget(request: Request, budget_id: str) -> Any:
    result = services.configured_repository(request=request).get_budget(budget_id)
    if result is None:
        raise services.APIServiceError(404, "budget_not_found", "Budget was not found.")
    return success(request, result)


@router.get("/budgets/{budget_id}/history")
async def budget_history(request: Request, budget_id: str) -> Any:
    repository = services.configured_repository(request=request)
    if repository.get_budget(budget_id) is None:
        raise services.APIServiceError(404, "budget_not_found", "Budget was not found.")
    return success(request, repository.list_budget_revisions(budget_id))


@router.get("/research")
async def list_research(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    profile_id: str | None = None,
) -> Any:
    items, total = services.configured_repository(request=request).list_research_runs(
        profile_id=profile_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success(request, _page_data(items, total, page, page_size))


@router.get("/research/{research_id}")
async def get_research(request: Request, research_id: str) -> Any:
    result = services.configured_repository(request=request).get_research_run(research_id)
    if result is None:
        raise services.APIServiceError(404, "research_not_found", "Research run was not found.")
    return success(request, result)


@router.get("/reports")
async def list_reports(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    profile_id: str | None = None,
) -> Any:
    items, total = services.configured_repository(request=request).list_reports(
        profile_id=profile_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success(request, _page_data(items, total, page, page_size))


@router.get("/reports/{report_id}")
async def get_report(request: Request, report_id: str) -> Any:
    result = services.configured_repository(request=request).get_report(report_id)
    if result is None:
        raise services.APIServiceError(404, "report_not_found", "Report was not found.")
    return success(request, result)


@router.get("/reports/{report_id}/download")
async def download_report(
    request: Request,
    report_id: str,
    format: Literal["json", "markdown"] = "json",
) -> Any:
    result = services.configured_repository(request=request).get_report(report_id)
    if result is None:
        raise services.APIServiceError(404, "report_not_found", "Report was not found.")
    report = result["result"]
    if format == "json":
        data = {
            "format": "json",
            "filename": f"{report_id}.json",
            "content": report,
        }
    else:
        data = {
            "format": "markdown",
            "filename": f"{report_id}.md",
            "content": _report_markdown(report),
        }
    filename = data["filename"]
    return success(
        request,
        data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise services.APIServiceError(
            422,
            "invalid_json",
            "Request body is not valid JSON.",
        ) from exc


def _page_data(items: list[dict[str, Any]], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def _report_markdown(report: dict[str, Any]) -> str:
    sections = report.get("sections") or {}
    lines = [
        "# Financial report",
        "",
        str(sections.get("summary", "No report summary.")),
    ]
    for heading, key in (
        ("Spending insights", "spending_insights"),
        ("Savings opportunities", "savings_opportunities"),
        ("Risk considerations", "risk_considerations"),
    ):
        entries = sections.get(key) or []
        if entries:
            lines.extend(["", f"## {heading}", ""])
            lines.extend(f"- {entry}" for entry in entries)
    findings = sections.get("research_findings") or []
    if findings:
        lines.extend(["", "## Research findings", ""])
        lines.extend(
            f"- {finding.get('statement', '')} (Sources: {', '.join(finding.get('source_ids', []))})"
            for finding in findings
        )
    return "\n".join(lines) + "\n"
