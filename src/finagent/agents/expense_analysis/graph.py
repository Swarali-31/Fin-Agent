"""LangGraph workflow for deterministic and LLM-assisted expense analysis."""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from finagent.agents.expense_analysis.calculations import ExpenseMetrics, compute_expense_metrics
from finagent.agents.expense_analysis.prompts import (
    SYSTEM_PROMPT,
    ExpenseInterpretation,
    interpretation_prompt,
)
from finagent.schemas.common import AgentError, AgentName, AgentStatus, ExpenseCategory, Limitation
from finagent.schemas.expense import DataGap, ExpenseAnalysisRequest, ExpenseAnalysisResult, SpendingInsight
from finagent.schemas.financial import FinancialProfile


class _ExpenseState(TypedDict, total=False):
    request: Any
    profile: FinancialProfile
    metrics: ExpenseMetrics
    interpretation: ExpenseInterpretation
    verified_patterns: list[SpendingInsight]
    clarifying_questions: list[str]
    llm_error: bool
    result: ExpenseAnalysisResult


def _failed_result(code: str, message: str, details: dict[str, Any] | None = None) -> ExpenseAnalysisResult:
    return ExpenseAnalysisResult(
        status=AgentStatus.failed,
        errors=[AgentError(code=code, message=message, details=details)],
    )


def _request_error_details(error: ValidationError) -> list[dict[str, str]]:
    return [
        {
            "location": ".".join(str(part) for part in item["loc"]),
            "message": item["msg"],
        }
        for item in error.errors()
    ]


def _prompt_metrics(profile: FinancialProfile, metrics: ExpenseMetrics) -> dict[str, object]:
    return {
        "summary": metrics.summary.model_dump(mode="json"),
        "recurring_expenses": [item.model_dump(mode="json") for item in metrics.recurring_expenses],
        "unusual_transactions": [item.model_dump(mode="json") for item in metrics.unusual_transactions],
        "data_gaps": [item.model_dump(mode="json") for item in metrics.data_gaps],
        "categories": sorted(category.value for category in metrics.summary.category_totals),
        "transaction_ids": sorted(transaction.id for transaction in profile.transactions),
    }


def build_expense_analysis_graph(llm: Any | None = None) -> Any:
    """Build and compile the expense-analysis StateGraph.

    The LLM is injected for tests or supplied lazily by the configured FinAgent factory.
    """

    def validate_input(state: _ExpenseState) -> dict[str, Any]:
        try:
            request = ExpenseAnalysisRequest.model_validate(state.get("request"))
        except ValidationError as exc:
            return {
                "result": _failed_result(
                    "invalid_input",
                    "The expense analysis request did not match the shared schema.",
                    {"validation_errors": _request_error_details(exc)},
                )
            }
        return {"profile": request.profile}

    def route_after_validation(state: _ExpenseState) -> str:
        return "finish" if state.get("result") is not None else "compute_metrics"

    def compute_metrics(state: _ExpenseState) -> dict[str, Any]:
        try:
            return {"metrics": compute_expense_metrics(state["profile"])}
        except Exception:
            return {
                "result": _failed_result(
                    "calculation_failed",
                    "Deterministic expense calculations could not be completed.",
                )
            }

    def route_after_compute(state: _ExpenseState) -> str:
        return "finish" if state.get("result") is not None else "interpret"

    def interpret(state: _ExpenseState) -> dict[str, Any]:
        try:
            model = llm
            if model is None:
                from finagent.llm import get_llm

                model = get_llm()
            structured_model = model.with_structured_output(ExpenseInterpretation)
            output = structured_model.invoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=interpretation_prompt(_prompt_metrics(state["profile"], state["metrics"]))),
                ]
            )
            interpretation = ExpenseInterpretation.model_validate(output)
            return {"interpretation": interpretation}
        except Exception:
            return {"llm_error": True, "interpretation": ExpenseInterpretation()}

    def verify_interpretation(state: _ExpenseState) -> dict[str, Any]:
        allowed_categories = {
            category.value for category in state["metrics"].summary.category_totals
        }
        allowed_ids = {transaction.id for transaction in state["profile"].transactions}
        patterns: list[SpendingInsight] = []
        for insight in state["interpretation"].spending_patterns:
            if any(category not in allowed_categories for category in insight.categories):
                continue
            if any(transaction_id not in allowed_ids for transaction_id in insight.transaction_ids):
                continue
            patterns.append(
                SpendingInsight(
                    title=insight.title,
                    detail=insight.detail,
                    categories=[ExpenseCategory(category) for category in insight.categories],
                )
            )
        return {
            "verified_patterns": patterns,
            "clarifying_questions": state["interpretation"].clarifying_questions,
        }

    def assemble(state: _ExpenseState) -> dict[str, Any]:
        metrics = state["metrics"]
        data_gaps = list(metrics.data_gaps)
        data_gaps.extend(
            # Shared output models represent clarification questions as open data gaps.
            DataGap(
                issue="clarification_question",
                question=question,
            )
            for question in state.get("clarifying_questions", [])
        )
        llm_error = state.get("llm_error", False)
        return {
            "result": ExpenseAnalysisResult(
                status=AgentStatus.partial if llm_error else AgentStatus.success,
                limitations=(
                    [
                        Limitation(
                            code="llm_interpretation_unavailable",
                            message="Language-model interpretation was unavailable; deterministic results are included.",
                        )
                    ]
                    if llm_error
                    else []
                ),
                analysis_version=metrics.analysis_version,
                summary=metrics.summary,
                recurring_expenses=metrics.recurring_expenses,
                unusual_transactions=metrics.unusual_transactions,
                spending_patterns=state.get("verified_patterns", []),
                data_gaps=data_gaps,
            )
        }

    graph = StateGraph(_ExpenseState)
    graph.add_node("validate_input", validate_input)
    graph.add_node("compute_metrics", compute_metrics)
    graph.add_node("interpret", interpret)
    graph.add_node("verify_interpretation", verify_interpretation)
    graph.add_node("assemble", assemble)
    graph.add_edge(START, "validate_input")
    graph.add_conditional_edges(
        "validate_input",
        route_after_validation,
        {"finish": END, "compute_metrics": "compute_metrics"},
    )
    graph.add_conditional_edges(
        "compute_metrics",
        route_after_compute,
        {"finish": END, "interpret": "interpret"},
    )
    graph.add_edge("interpret", "verify_interpretation")
    graph.add_edge("verify_interpretation", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def run_expense_analysis(
    request: ExpenseAnalysisRequest | dict[str, Any],
    llm: Any | None = None,
) -> ExpenseAnalysisResult:
    """Run expense analysis and return expected failures as structured results."""
    try:
        state = build_expense_analysis_graph(llm=llm).invoke({"request": request})
        result = state.get("result")
        if isinstance(result, ExpenseAnalysisResult):
            return result
        return _failed_result("missing_result", "Expense analysis completed without a result.")
    except Exception:
        return _failed_result("agent_execution_error", "Expense analysis could not be completed.")