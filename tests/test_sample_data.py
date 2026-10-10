"""Tests for sample financial data."""

from __future__ import annotations

from decimal import Decimal

from finagent.sample_data import (
    max_achievable_monthly_savings,
    profile_monthly_averages,
    sample_profile,
    sample_research_question,
    sample_savings_goal_feasible,
    sample_savings_goal_infeasible,
    verify_sample_data,
)


def test_sample_profile_validates() -> None:
    profile = sample_profile()
    assert profile.currency == "INR"
    assert len(profile.transactions) >= 1
    ids = {t.id for t in profile.transactions}
    assert len(ids) == len(profile.transactions)


def test_sample_data_monthly_averages() -> None:
    profile = sample_profile()
    income, expenses, surplus = profile_monthly_averages(profile)
    assert income == Decimal("85000.00")
    assert expenses == Decimal("76264.67")
    assert surplus == Decimal("8735.33")


def test_savings_goals_feasibility_claims() -> None:
    verify_sample_data()
    profile = sample_profile()
    feasible = sample_savings_goal_feasible()
    infeasible = sample_savings_goal_infeasible()
    assert feasible.monthly_target is not None
    assert infeasible.monthly_target is not None
    _, _, current_surplus = profile_monthly_averages(profile)
    assert current_surplus < feasible.monthly_target.amount
    assert max_achievable_monthly_savings(profile) >= feasible.monthly_target.amount
    assert infeasible.monthly_target.amount > max_achievable_monthly_savings(profile)


def test_sample_research_question_non_empty() -> None:
    q = sample_research_question()
    assert "SIP" in q or "sip" in q.lower()
    assert len(q) > 40
