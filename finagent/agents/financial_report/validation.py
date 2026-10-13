"""Pure consistency checks across financial report inputs."""

from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit

from finagent.schemas.common import Severity, ValidationStatus
from finagent.schemas.report import ReportRequest, ValidationIssue


_ERROR_MESSAGES = {
    "STALE_BUDGET": "the budget was built from a different expense analysis",
    "STALE_ANALYSIS": "the expense analysis does not match the requested version",
    "CURRENCY_MISMATCH": "the expense analysis and budget use different currencies",
    "PERIOD_MISMATCH": "the budget's current spending does not match the analysis period averages",
    "ANALYSIS_FAILED": "the expense analysis failed",
    "BUDGET_FAILED": "the budget plan failed",
    "MISSING_ANALYSIS_VERSION": "the expense analysis has no version",
    "MISSING_BUDGET_VERSION": "the budget has no version",
    "MISSING_ANALYSIS_SUMMARY": "the expense analysis has no financial summary",
    "SURPLUS_INCONSISTENT": "the expense summary surplus does not equal income minus expenses",
    "EXPENSE_TOTAL_INCONSISTENT": "the expense category totals do not equal monthly expenses",
    "BUDGET_OVER_INCOME": "budget category limits and planned savings exceed income",
}

_WARNING_MESSAGES = {
    "RESEARCH_MISSING": "research evidence was not supplied",
    "RESEARCH_FAILED": "the research step failed",
    "RESEARCH_PARTIAL": "research is incomplete",
    "ANALYSIS_PARTIAL": "the expense analysis is partial",
    "BUDGET_PARTIAL": "the budget plan is partial",
    "UNRESOLVED_DATA_GAPS": "the expense analysis contains unresolved data gaps",
    "INFEASIBLE_SAVINGS": "the requested savings target is infeasible",
    "SOURCE_URL_MISSING": "a research finding refers to a source without a usable URL",
}


def _issue(code: str, severity: Severity) -> ValidationIssue:
    messages = _ERROR_MESSAGES if severity == Severity.error else _WARNING_MESSAGES
    return ValidationIssue(
        code=code,
        severity=severity,
        message=messages[code],
    )


def validate_report_request(request: ReportRequest) -> list[ValidationIssue]:
    """Return stable validation issues without mutating or recomputing inputs."""
    issues: list[ValidationIssue] = []
    analysis = request.expense_analysis
    budget = request.budget
    summary = analysis.summary

    if analysis.status.value == "failed":
        issues.append(_issue("ANALYSIS_FAILED", Severity.error))
    if budget.status.value == "failed":
        issues.append(_issue("BUDGET_FAILED", Severity.error))
    if not analysis.analysis_version:
        issues.append(_issue("MISSING_ANALYSIS_VERSION", Severity.error))
    if not budget.budget_id:
        issues.append(_issue("MISSING_BUDGET_VERSION", Severity.error))
    if summary is None:
        issues.append(_issue("MISSING_ANALYSIS_SUMMARY", Severity.error))
    else:
        if (
            analysis.analysis_version
            and budget.source_analysis_version != analysis.analysis_version
        ):
            issues.append(_issue("STALE_BUDGET", Severity.error))
        if (
            request.expected_analysis_version is not None
            and request.expected_analysis_version != analysis.analysis_version
        ):
            issues.append(_issue("STALE_ANALYSIS", Severity.error))
        if budget.currency != summary.currency:
            issues.append(_issue("CURRENCY_MISMATCH", Severity.error))

        current_by_category = {
            item.category: item.current_monthly_spend.amount
            for item in budget.category_limits
        }
        summary_by_category = {
            category: amount.amount
            for category, amount in summary.category_totals.items()
        }
        if current_by_category != summary_by_category:
            issues.append(_issue("PERIOD_MISMATCH", Severity.error))

        calculated_surplus = (
            summary.monthly_income.amount - summary.monthly_expenses.amount
        ).quantize(Decimal("0.01"))
        if calculated_surplus != summary.available_surplus.amount:
            issues.append(_issue("SURPLUS_INCONSISTENT", Severity.error))
        category_total = sum(
            summary_by_category.values(),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        if category_total != summary.monthly_expenses.amount:
            issues.append(_issue("EXPENSE_TOTAL_INCONSISTENT", Severity.error))

    budget_total = (
        sum(
            (item.monthly_limit.amount for item in budget.category_limits),
            Decimal("0.00"),
        )
        + budget.planned_monthly_savings.amount
    ).quantize(Decimal("0.01"))
    if budget_total > budget.monthly_income.amount:
        issues.append(_issue("BUDGET_OVER_INCOME", Severity.error))

    if request.research is None:
        issues.append(_issue("RESEARCH_MISSING", Severity.warning))
    elif request.research.status.value == "failed":
        issues.append(_issue("RESEARCH_FAILED", Severity.warning))
    elif request.research.status.value == "partial":
        issues.append(_issue("RESEARCH_PARTIAL", Severity.warning))
    if analysis.status.value == "partial":
        issues.append(_issue("ANALYSIS_PARTIAL", Severity.warning))
    if budget.status.value == "partial":
        issues.append(_issue("BUDGET_PARTIAL", Severity.warning))
    if analysis.data_gaps:
        issues.append(_issue("UNRESOLVED_DATA_GAPS", Severity.warning))
    if not budget.feasibility.is_feasible:
        issues.append(_issue("INFEASIBLE_SAVINGS", Severity.warning))

    if request.research is not None:
        sources_by_id = {
            source.source_id: source
            for source in request.research.sources
        }
        if any(
            not _has_usable_url(sources_by_id[source_id].url)
            for finding in request.research.findings
            for source_id in finding.source_ids
            if source_id in sources_by_id
        ):
            issues.append(_issue("SOURCE_URL_MISSING", Severity.warning))

    return issues


def _has_usable_url(url: object) -> bool:
    try:
        parsed = urlsplit(str(url))
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validation_summary(issues: list[ValidationIssue]) -> str:
    """Summarize the validation state and translate codes into plain language."""
    errors = [item for item in issues if item.severity == Severity.error]
    if errors:
        descriptions = "; ".join(
            f"{item.code}: {_ERROR_MESSAGES.get(item.code, item.message)}"
            for item in errors
        )
        return f"Rejected: {descriptions}."

    warnings = [item for item in issues if item.severity == Severity.warning]
    if warnings:
        descriptions = "; ".join(
            f"{item.code}: {_WARNING_MESSAGES.get(item.code, item.message)}"
            for item in warnings
        )
        return f"Flagged: {descriptions}."
    return "Valid: all upstream inputs are consistent."


def validation_status(issues: list[ValidationIssue]) -> ValidationStatus:
    """Map validation severities to the shared validation status."""
    if any(item.severity == Severity.error for item in issues):
        return ValidationStatus.rejected
    if any(item.severity == Severity.warning for item in issues):
        return ValidationStatus.flagged
    return ValidationStatus.valid
