"""The screenshot's savings question works with all model/search calls disabled."""
from backend.tests.test_auth_workspace import accounts, register
from backend.app.services.adapters.financial_research import FinancialResearchAdapter


def test_savings_question_in_bengali_works_and_is_saved_during_outage(accounts, monkeypatch):
    first, _ = accounts
    account = register(first, "cashflow-test@example.invalid")
    profile = account["profile_id"]
    response = first.post(f"/api/v1/profiles/{profile}/transactions", json={"transactions":[
        {"id":"salary", "date":"2026-10-01", "description":"TEST salary", "type":"income", "amount":"80000.00"},
        {"id":"rent", "date":"2026-10-02", "description":"TEST rent", "type":"expense", "category":"housing", "amount":"55000.00"},
    ]})
    assert response.status_code == 200
    def unavailable(*args, **kwargs):
        raise AssertionError("Neither search nor model should run for saved arithmetic")
    monkeypatch.setattr(FinancialResearchAdapter, "resolve_llm", unavailable)
    monkeypatch.setattr(FinancialResearchAdapter, "_configured_search_provider", unavailable)
    response = first.post(f"/api/v1/agents/financial-research/run?profile_id={profile}", json={
        "question":"Based on my spending, how much could I save each month?",
        "response_language":"Bengali", "response_detail":"detailed",
    })
    assert response.status_code == 200, response.text
    result = response.json()["data"]["result"]
    assert result["status"] == "success"
    assert "25,000.00 INR" in result["calculated_answer"]
    assert "সঞ্চয়ের" in result["calculated_answer"]
    assert not result["limitations"] and not result["sources"]
    history = first.get(f"/api/v1/research?profile_id={profile}").json()["data"]["items"]
    assert history[0]["result"]["calculated_answer"] == result["calculated_answer"]
