"""LangGraph workflow for validating and composing financial reports."""

from __future__ import annotations

import re
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from finagent.agents.financial_report.prompts import (
    SYSTEM_PROMPT,
    ReportComposition,
    composition_prompt,
)
from finagent.agents.financial_report.validation import (
    validate_report_request,
    validation_status,
    validation_summary,
)
from finagent.schemas.common import (
    AgentError,
    AgentStatus,
    Limitation,
    Severity,
    ValidationStatus,
    compute_version,
)
from finagent.schemas.report import (
    FinancialReport,
    ReportRequest,
    ReportSections,
    ReportSourceVersions,
    ValidationIssue,
)

_URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
_SOURCE_ID_RE = re.compile(r"\bS\d+\b")
_NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:[$€£₹]\s*)?\d+(?:[.,]\d+)*(?:\s*%)?(?![A-Za-z])")
_DISCLAIMER = "This report is informational and does not constitute personalized financial advice."
_FALLBACK_SUMMARY = (
    "This report summarizes the supplied financial analysis and budget alongside any "
    "available research. Review the included assumptions, data limitations, and risks "
    "before making independent financial decisions."
)


class _ReportState(TypedDict, total=False):
    request: Any
    parsed_request: ReportRequest
    validation_issues: list[ValidationIssue]
    validation_status: ValidationStatus
    validation_summary: str
    composition: ReportComposition
    sections: ReportSections
    limitations: list[Limitation]
    llm_failed: bool
    deterministic_fallback: bool
    result: FinancialReport


def _research_content(request: ReportRequest) -> dict[str, object]:
    research = request.research
    if research is None:
        return {"findings": [], "sources": []}
    return {
        "findings": [
            {
                "statement": finding.statement,
                "source_ids": finding.source_ids,
                "confidence": finding.confidence,
            }
            for finding in research.findings
        ],
        "sources": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "url": str(source.url),
                "publisher": source.publisher,
                "published_date": source.published_date.isoformat()
                if source.published_date
                else None,
                "tier": source.tier.value,
                "snippet": source.snippet,
            }
            for source in research.sources
        ],
        "status": research.status.value,
        "limitations": [
            {"code": issue.code, "message": issue.message}
            for issue in research.limitations
        ],
    }


def _report_version(request: ReportRequest) -> str:
    analysis_version = request.expense_analysis.analysis_version or ""
    budget_id = request.budget.budget_id or ""
    return compute_version(
        "fr",
        {
            "analysis_version": analysis_version,
            "budget_id": budget_id,
            "budget_revision": request.budget.revision,
            "research": _research_content(request),
        },
    )


def _source_versions(request: ReportRequest) -> ReportSourceVersions:
    return ReportSourceVersions(
        analysis_version=request.expense_analysis.analysis_version or "",
        budget_id=request.budget.budget_id or "",
        budget_revision=request.budget.revision,
    )


def _qualitative_context(request: ReportRequest) -> dict[str, object]:
    analysis = request.expense_analysis
    summary = analysis.summary
    budget = request.budget
    return {
        "question": request.research.question if request.research else None,
        "spending_insights": [
            {
                "title": insight.title,
                "detail": insight.detail,
                "categories": [category.value for category in insight.categories],
            }
            for insight in analysis.spending_patterns
        ],
        "data_gaps": [gap.issue for gap in analysis.data_gaps],
        "budget_feasible": budget.feasibility.is_feasible,
        "budget_trade_offs": budget.trade_offs,
        "research_findings": [
            finding.statement for finding in request.research.findings
        ]
        if request.research
        else [],
        "period": (
            f"{summary.period_start} through {summary.period_end}"
            if summary
            else None
        ),
    }


def _clean_narrative(
    text: str,
    *,
    known_urls: set[str],
    known_source_ids: set[str],
) -> str:
    def keep_url(match: re.Match[str]) -> str:
        candidate = match.group(0).rstrip(".,;:")
        trailing = match.group(0)[len(candidate) :]
        return match.group(0) if candidate in known_urls else trailing

    def keep_source_id(match: re.Match[str]) -> str:
        token = match.group(0)
        return token if token in known_source_ids else ""

    text = _URL_RE.sub(keep_url, text)
    return _SOURCE_ID_RE.sub(keep_source_id, text).strip()


def _narrative_has_numbers(composition: ReportComposition) -> bool:
    values = [
        composition.summary,
        *composition.spending_insights,
        *composition.savings_opportunities,
        *composition.risk_considerations,
    ]
    return any(
        _NUMBER_RE.search(_SOURCE_ID_RE.sub("", value))
        for value in values
    )


def _assemble_sections(
    request: ReportRequest,
    composition: ReportComposition,
) -> ReportSections:
    sources = request.research.sources if request.research else []
    source_ids = {source.source_id for source in sources}
    urls = {str(source.url) for source in sources}
    narrative_values = [
        _clean_narrative(
            item,
            known_urls=urls,
            known_source_ids=source_ids,
        )
        for item in (
            composition.summary,
            *composition.spending_insights,
            *composition.savings_opportunities,
            *composition.risk_considerations,
        )
    ]
    summary, *remaining = narrative_values
    spending_count = len(composition.spending_insights)
    savings_count = len(composition.savings_opportunities)
    risk_count = len(composition.risk_considerations)
    return ReportSections(
        summary=summary,
        spending_insights=remaining[:spending_count],
        budget_overview=list(request.budget.category_limits),
        savings_opportunities=remaining[
            spending_count : spending_count + savings_count
        ],
        research_findings=list(request.research.findings) if request.research else [],
        sources=list(sources),
        assumptions=list(request.budget.assumptions),
        risk_considerations=remaining[
            spending_count + savings_count :
            spending_count + savings_count + risk_count
        ],
    )


def _rejection(
    request: ReportRequest,
    issues: list[ValidationIssue],
    summary: str,
) -> FinancialReport:
    return FinancialReport(
        status=AgentStatus.failed,
        report_version=None,
        validation_status=ValidationStatus.rejected,
        validation_issues=issues,
        validation_summary=summary,
        source_versions=None,
        sections=None,
        limitations=[],
    )


def build_report_graph(llm: Any | None = None) -> Any:
    """Build and compile the report validation/composition StateGraph."""

    def validate(state: _ReportState) -> dict[str, Any]:
        try:
            request = ReportRequest.model_validate(state.get("request"))
        except ValidationError as exc:
            issue = ValidationIssue(
                code="INVALID_REQUEST",
                severity=Severity.error,
                message="The report request does not match the shared schema.",
            )
            summary = "Rejected: INVALID_REQUEST: the report request is invalid."
            return {
                "validation_issues": [issue],
                "validation_status": ValidationStatus.rejected,
                "validation_summary": summary,
                "result": FinancialReport(
                    status=AgentStatus.failed,
                    validation_status=ValidationStatus.rejected,
                    validation_issues=[issue],
                    validation_summary=summary,
                    sections=None,
                    source_versions=None,
                    report_version=None,
                    errors=[
                        AgentError(
                            code="invalid_request",
                            message="The report request did not match the shared schema.",
                            details={
                                "validation_errors": [
                                    {
                                        "location": ".".join(str(part) for part in item["loc"]),
                                        "message": item["msg"],
                                    }
                                    for item in exc.errors()
                                ]
                            },
                        )
                    ],
                ),
            }
        issues = validate_report_request(request)
        state_status = validation_status(issues)
        summary = validation_summary(issues)
        return {
            "parsed_request": request,
            "validation_issues": issues,
            "validation_status": state_status,
            "validation_summary": summary,
        }

    def route_after_validate(state: _ReportState) -> str:
        if state.get("result") is not None:
            return "finish"
        return (
            "assemble_rejection"
            if state["validation_status"] == ValidationStatus.rejected
            else "compose"
        )

    def assemble_rejection(state: _ReportState) -> dict[str, Any]:
        request = state["parsed_request"]
        return {
            "result": _rejection(
                request,
                state["validation_issues"],
                state["validation_summary"],
            )
        }

    def compose(state: _ReportState) -> dict[str, Any]:
        if llm is False:
            return {"deterministic_fallback": True}
        try:
            model = llm
            if model is None:
                from finagent.llm import get_llm

                model = get_llm()
            structured_model = model.with_structured_output(ReportComposition)
            response = structured_model.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(
                        content=composition_prompt(
                            _qualitative_context(state["parsed_request"])
                        )
                    ),
                ]
            )
            return {"composition": ReportComposition.model_validate(response)}
        except Exception:
            return {"llm_failed": True}

    def verify_composition(state: _ReportState) -> dict[str, Any]:
        request = state["parsed_request"]
        limitations: list[Limitation] = []
        composition = state.get("composition")
        if (
            composition is None
            or state.get("deterministic_fallback")
            or _narrative_has_numbers(composition)
        ):
            if composition is not None:
                limitations.append(
                    Limitation(
                        code="composition_figures_removed",
                        message=(
                            "LLM-generated figures were omitted; numeric content is copied "
                            "only from validated upstream structures."
                        ),
                    )
                )
            composition = ReportComposition(
                summary=_FALLBACK_SUMMARY,
                spending_insights=[
                    insight.detail
                    for insight in request.expense_analysis.spending_patterns
                ],
                savings_opportunities=(
                    [
                        "Review the supplied budget categories and feasibility suggestions."
                    ]
                    if request.budget.feasibility.suggestions
                    else []
                ),
                risk_considerations=[
                    gap.question for gap in request.expense_analysis.data_gaps
                ],
            )
            if state.get("llm_failed"):
                limitations.append(
                    Limitation(
                        code="llm_composition_unavailable",
                        message="LLM composition failed; a deterministic template summary was used.",
                    )
                )
        sections = _assemble_sections(request, composition)
        return {"sections": sections, "limitations": limitations}

    def assemble(state: _ReportState) -> dict[str, Any]:
        request = state["parsed_request"]
        validation_issues = state["validation_issues"]
        report_status = (
            AgentStatus.partial
            if state["validation_status"] == ValidationStatus.flagged
            or state.get("limitations")
            else AgentStatus.success
        )
        return {
            "result": FinancialReport(
                status=report_status,
                report_version=_report_version(request),
                validation_status=state["validation_status"],
                validation_issues=validation_issues,
                validation_summary=state["validation_summary"],
                source_versions=_source_versions(request),
                sections=state["sections"],
                limitations=state.get("limitations", []),
            )
        }

    graph = StateGraph(_ReportState)
    graph.add_node("validate", validate)
    graph.add_node("assemble_rejection", assemble_rejection)
    graph.add_node("compose", compose)
    graph.add_node("verify_composition", verify_composition)
    graph.add_node("assemble", assemble)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {
            "finish": END,
            "assemble_rejection": "assemble_rejection",
            "compose": "compose",
        },
    )
    graph.add_edge("assemble_rejection", END)
    graph.add_edge("compose", "verify_composition")
    graph.add_edge("verify_composition", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def run_financial_report(
    request: ReportRequest | dict[str, Any],
    llm: Any | None = None,
) -> FinancialReport:
    """Validate and compose a report, returning expected failures as results."""
    try:
        state = build_report_graph(llm=llm).invoke({"request": request})
        result = state.get("result")
        if isinstance(result, FinancialReport):
            return result
    except Exception as exc:
        try:
            parsed = ReportRequest.model_validate(request)
        except ValidationError:
            parsed = None
        if parsed is not None:
            issue = ValidationIssue(
                code="REPORT_EXECUTION_FAILED",
                severity=Severity.error,
                message="The report could not be completed.",
            )
            return FinancialReport(
                status=AgentStatus.failed,
                validation_status=ValidationStatus.rejected,
                validation_issues=[issue],
                validation_summary="Rejected: REPORT_EXECUTION_FAILED: the report could not be completed.",
                source_versions=None,
                sections=None,
                errors=[
                    AgentError(
                        code="report_execution_failed",
                        message="The report could not be completed.",
                    )
                ],
            )
        return FinancialReport(
            status=AgentStatus.failed,
            validation_status=ValidationStatus.rejected,
            validation_issues=[
                ValidationIssue(
                    code="INVALID_REQUEST",
                    severity=Severity.error,
                    message="The report request does not match the shared schema.",
                )
            ],
            validation_summary="Rejected: INVALID_REQUEST: the report request is invalid.",
            source_versions=None,
            sections=None,
            errors=[
                AgentError(
                    code="invalid_request",
                    message="The report request did not match the shared schema.",
                )
            ],
        )
    return FinancialReport(
        status=AgentStatus.failed,
        validation_status=ValidationStatus.rejected,
        validation_issues=[
            ValidationIssue(
                code="REPORT_RESULT_MISSING",
                severity=Severity.error,
                message="The report graph completed without a report.",
            )
        ],
        validation_summary="Rejected: REPORT_RESULT_MISSING: the report graph returned no result.",
        source_versions=None,
        sections=None,
        errors=[
            AgentError(
                code="report_result_missing",
                message="The report graph completed without a report.",
            )
        ],
    )
