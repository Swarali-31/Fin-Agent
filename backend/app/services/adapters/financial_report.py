"""Adapter for report validation and composition."""

from __future__ import annotations

from typing import Any

from finagent.agents.financial_report.graph import run_financial_report
from finagent.schemas.report import ReportRequest
from pydantic import ValidationError

from backend.app.schemas.common import AdapterStatus, AgentEnvelope
from backend.app.services.adapters.base import (
    AgentAdapterBase,
    Context,
    begin_timing,
)


class FinancialReportAdapter(AgentAdapterBase):
    name = "financial_report"
    capabilities_list = ("financial_report", "upstream_consistency_validation")

    async def run(self, input: Any, context: Context = None) -> AgentEnvelope:
        started_at, started_counter = begin_timing()
        try:
            request = ReportRequest.model_validate(input)
        except ValidationError as exc:
            return self.validation_failure(
                input_value=input,
                error=exc,
                started_at=started_at,
                started_counter=started_counter,
            )
        try:
            llm = self.resolve_llm(context)
        except Exception as exc:
            return self.failed_envelope(
                input_value=input,
                started_at=started_at,
                started_counter=started_counter,
                code="misconfigured",
                message=str(exc),
            )
        return await self.invoke(
            input_value=input,
            operation=lambda: run_financial_report(request, llm=llm),
            started_at=started_at,
            started_counter=started_counter,
        )

    def status(self) -> AdapterStatus:
        return super().status()
