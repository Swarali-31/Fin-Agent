"""Financial report agent I/O models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from finagent.schemas.budget import BudgetPlan, CategoryBudget
from finagent.schemas.common import AgentName, AgentResultBase, Severity, ValidationStatus
from finagent.schemas.expense import ExpenseAnalysisResult
from finagent.schemas.research import ResearchFinding, ResearchResult, SourceMetadata


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    message: str


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_analysis: ExpenseAnalysisResult
    budget: BudgetPlan
    research: ResearchResult | None = None
    expected_analysis_version: str | None = None


class ReportSourceVersions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_version: str
    budget_id: str
    budget_revision: int = Field(..., ge=1)


class ReportSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    spending_insights: list[str] = Field(default_factory=list)
    budget_overview: list[CategoryBudget] = Field(default_factory=list)
    savings_opportunities: list[str] = Field(default_factory=list)
    research_findings: list[ResearchFinding] = Field(default_factory=list)
    sources: list[SourceMetadata] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risk_considerations: list[str] = Field(default_factory=list)


class FinancialReport(AgentResultBase):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName = AgentName.financial_report
    report_version: str | None = None
    validation_status: ValidationStatus
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    validation_summary: str
    source_versions: ReportSourceVersions | None = None
    sections: ReportSections | None = None
