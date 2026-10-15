"""Adapter for budget creation and revision."""

from __future__ import annotations

from typing import Any

from finagent.agents.budget_planning.graph import revise_budget, run_budget_planning
from finagent.schemas.budget import BudgetPlan, BudgetRequest
from finagent.schemas.expense import ExpenseAnalysisResult
from pydantic import ValidationError

from backend.app.schemas.common import AdapterStatus, AgentEnvelope
from backend.app.services.adapters.base import (
    AgentAdapterBase,
    Context,
    begin_timing,
)


class BudgetPlanningAdapter(AgentAdapterBase):
    name = "budget_planning"
    capabilities_list = ("create_budget", "revise_budget", "deterministic_baseline")

    async def create(self, request: Any, context: Context = None) -> AgentEnvelope:
        return await self.run(request, context)

    async def revise(
        self,
        previous: Any,
        new_analysis: Any,
        context: Context = None,
    ) -> AgentEnvelope:
        input_value = {
            "action": "revise",
            "previous": previous,
            "new_analysis": new_analysis,
        }
        started_at, started_counter = begin_timing()
        try:
            previous_plan = BudgetPlan.model_validate(previous)
            analysis = ExpenseAnalysisResult.model_validate(new_analysis)
        except ValidationError as exc:
            return self.validation_failure(
                input_value=input_value,
                error=exc,
                started_at=started_at,
                started_counter=started_counter,
            )
        try:
            llm = self.resolve_llm(context)
        except Exception as exc:
            return self.failed_envelope(
                input_value=input_value,
                started_at=started_at,
                started_counter=started_counter,
                code="misconfigured",
                message=str(exc),
            )
        return await self.invoke(
            input_value=input_value,
            operation=lambda: revise_budget(previous_plan, analysis, llm=llm),
            started_at=started_at,
            started_counter=started_counter,
        )

    async def run(self, input: Any, context: Context = None) -> AgentEnvelope:
        if isinstance(input, dict) and input.get("action") == "revise":
            return await self.revise(
                input.get("previous"),
                input.get("new_analysis"),
                context,
            )
        request_input = input.get("request", input) if isinstance(input, dict) else input
        started_at, started_counter = begin_timing()
        try:
            request = BudgetRequest.model_validate(request_input)
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
            operation=lambda: run_budget_planning(request, llm=llm),
            started_at=started_at,
            started_counter=started_counter,
        )

    def status(self) -> AdapterStatus:
        return super().status()
