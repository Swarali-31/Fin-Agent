from __future__ import annotations

import os

import pytest

from finagent.agents.expense_analysis.graph import run_expense_analysis
from finagent.schemas.common import AgentStatus
from finagent.sample_data import sample_profile


class FakeChatModel:
    def __init__(self, response: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error

    def with_structured_output(self, schema: type) -> FakeChatModel:
        self.schema = schema
        return self

    def invoke(self, messages: object) -> object:
        if self.error is not None:
            raise self.error
        return self.schema.model_validate(self.response)


def test_graph_returns_success_with_injected_structured_model() -> None:
    result = run_expense_analysis(
        {"profile": sample_profile().model_dump(mode="json")},
        llm=FakeChatModel(
            {
                "spending_patterns": [
                    {
                        "title": "Housing is consistent",
                        "detail": "The housing category follows a steady pattern.",
                        "categories": ["housing"],
                        "transaction_ids": ["exp-rent-2026-07"],
                    }
                ],
                "clarifying_questions": ["Can you clarify the uncategorized payments?"],
            }
        ),
    )

    assert result.status == AgentStatus.success
    assert result.summary is not None
    assert len(result.spending_patterns) == 1
    assert result.spending_patterns[0].categories[0].value == "housing"
    assert any(gap.issue == "clarification_question" for gap in result.data_gaps)


def test_invalid_input_returns_failed_result_without_raising() -> None:
    result = run_expense_analysis({"profile": {"profile_id": "broken"}}, llm=FakeChatModel())

    assert result.status == AgentStatus.failed
    assert result.errors[0].code == "invalid_input"
    assert result.summary is None


def test_llm_failure_returns_partial_deterministic_result() -> None:
    result = run_expense_analysis(
        {"profile": sample_profile().model_dump(mode="json")},
        llm=FakeChatModel(error=RuntimeError("provider unavailable")),
    )

    assert result.status == AgentStatus.partial
    assert result.summary is not None
    assert result.analysis_version is not None
    assert result.limitations[0].code == "llm_interpretation_unavailable"


def test_hallucinated_transaction_reference_drops_insight() -> None:
    result = run_expense_analysis(
        {"profile": sample_profile().model_dump(mode="json")},
        llm=FakeChatModel(
            {
                "spending_patterns": [
                    {
                        "title": "Unsupported reference",
                        "detail": "This insight cites a transaction not in the profile.",
                        "categories": ["housing"],
                        "transaction_ids": ["transaction-that-does-not-exist"],
                    },
                    {
                        "title": "Supported category",
                        "detail": "Housing entries form a recurring pattern.",
                        "categories": ["housing"],
                        "transaction_ids": ["exp-rent-2026-07"],
                    },
                ],
                "clarifying_questions": [],
            }
        ),
    )

    assert result.status == AgentStatus.success
    assert [insight.title for insight in result.spending_patterns] == ["Supported category"]


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("FINAGENT_RUN_LIVE_TESTS") != "1",
    reason="set FINAGENT_RUN_LIVE_TESTS=1 to exercise a configured provider",
)
def test_live_expense_analysis_smoke() -> None:
    result = run_expense_analysis({"profile": sample_profile().model_dump(mode="json")})
    assert result.status in (AgentStatus.success, AgentStatus.partial)
    assert result.summary is not None