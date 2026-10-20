"""Focused account isolation checks; no live services or real financial records."""
from datetime import date
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.app.auth.routes import _attempts
from backend.app.db.models import Base
from backend.app.db.session import create_session_factory
from backend.app.main import app
from backend.app.repositories import PostgresRepository


@pytest.fixture
def accounts():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    previous = {key: getattr(app.state, key, None) for key in ("repository", "agent_context", "adapters")}
    app.state.repository = PostgresRepository(create_session_factory(engine))
    app.state.agent_context = {"llm": False}
    app.state.adapters = None
    _attempts.clear()
    with TestClient(app) as first, TestClient(app) as second:
        yield first, second
    for key, value in previous.items():
        setattr(app.state, key, value)
    app.state.workflow_tasks = {}
    engine.dispose()


def register(client, email):
    response = client.post("/api/v1/auth/signup", json={"name": "TEST FIXTURE", "email": email, "password": "test-only-password", "currency": "INR"})
    assert response.status_code == 201, response.text
    assert "httponly" in response.headers["set-cookie"].lower()
    return response.json()["data"]


def test_accounts_own_profiles_transactions_and_workflows(accounts):
    first, second = accounts
    assert first.get("/api/v1/profiles").status_code == 401
    alice = register(first, "alice@example.invalid")
    bob = register(second, "bob@example.invalid")
    assert alice["profile_id"] != bob["profile_id"]
    assert first.get("/api/v1/auth/me").json()["data"]["email"] == alice["email"]
    rows = [{"id": "salary", "date": date.today().isoformat(), "description": "TEST FIXTURE income", "amount": "80000.00", "type": "income"},
            {"id": "rent", "date": date.today().isoformat(), "description": "TEST FIXTURE housing", "amount": "20000.00", "type": "expense", "category": "housing"}]
    path = f"/api/v1/profiles/{alice['profile_id']}/transactions"
    assert first.post(path, json={"transactions": rows}).status_code == 200
    assert first.get(f"/api/v1/profiles/{alice['profile_id']}/summary").status_code == 200
    assert first.get(f"/api/v1/profiles/{alice['profile_id']}/expense-analyses/latest").status_code == 404
    assert second.get(path).status_code == 404
    assert second.post(path, json={"transactions": rows}).status_code == 404
    own = second.get("/api/v1/profiles").json()["data"]
    assert [profile["profile_id"] for profile in own] == [bob["profile_id"]]
    response = first.post("/api/v1/workflows", json={"task": "Generate a financial report", "context": {"profile_id": alice["profile_id"]}})
    assert response.status_code == 202, response.text
    run_id = response.json()["data"]["run_id"]
    for _ in range(100):
        result = first.get(f"/api/v1/workflows/{run_id}").json()["data"]
        if result["status"] != "running":
            break
        time.sleep(.02)
    assert result["status"] in {"success", "partial"}, result
    assert second.get(f"/api/v1/workflows/{run_id}").status_code == 404
    assert second.get(f"/api/v1/workflows/{run_id}/trace").status_code == 404
    assert second.get("/api/v1/workflows").json()["data"]["total"] == 0
    reports = first.get("/api/v1/reports").json()["data"]
    assert reports["total"] == 1
    report_id = reports["items"][0]["id"]
    pdf = first.get(f"/api/v1/reports/{report_id}/download?format=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-")
    assert second.get(f"/api/v1/reports/{report_id}/download?format=pdf").status_code == 404
    assert second.get(f"/api/v1/reports/{report_id}").status_code == 404
    assert second.get("/api/v1/reports").json()["data"]["total"] == 0
    assert first.post("/api/v1/auth/logout").status_code == 200
    assert first.get("/api/v1/profiles").status_code == 401
    assert first.post("/api/v1/auth/login", json={"email": alice["email"], "password": "wrong-password"}).status_code == 401
    assert first.post("/api/v1/auth/login", json={"email": alice["email"], "password": "test-only-password"}).status_code == 200
    assert len(first.get(path).json()["data"]["transactions"]) == 2


def test_csv_preview_and_correction_are_scoped_and_invalidate_analysis(accounts):
    first,second=accounts
    alice=register(first,'import-alice@example.invalid'); register(second,'import-bob@example.invalid')
    profile=alice['profile_id'];path=f'/api/v1/profiles/{profile}'
    csv_text='Transaction Date,Narration,Debit,Credit\n2026-01-01,TEST FIXTURE salary,,1000\n2026-01-02,TEST FIXTURE rent,200,\n'
    assert second.post(path+'/imports/preview',json={'csv_text':csv_text}).status_code==404
    response=first.post(path+'/imports/preview',json={'csv_text':csv_text})
    assert response.status_code==200
    assert first.get(path+'/transactions').json()['data']['transactions']==[]
    rows=[item['transaction'] for item in response.json()['data']['rows']]
    assert first.post(path+'/transactions',json={'transactions':rows}).status_code==200
    assert first.post('/api/v1/agents/expense-analysis/run',json={'profile_id':profile}).status_code==200
    assert first.get(path+'/expense-analyses/latest').json()['data']['is_current'] is True
    corrected={**rows[0],'amount':{'amount':'1200.00'}}
    edit_path=path+f'/transactions/{rows[0]["id"]}/correct'
    assert second.post(edit_path,json=corrected).status_code==404
    assert first.post(edit_path,json=corrected).status_code==200
    assert first.get(path+'/expense-analyses/latest').json()['data']['is_current'] is False
    budget=first.post('/api/v1/agents/budget-planning/run?profile_id='+profile,json={})
    assert budget.status_code==409
    assert budget.json()['error']['code']=='stale_analysis'


def test_selected_transactions_can_be_deleted_and_restored_without_cross_account_access(accounts):
    first, second = accounts
    alice = register(first, "selection-alice@example.invalid")
    register(second, "selection-bob@example.invalid")
    base = f"/api/v1/profiles/{alice['profile_id']}"
    rows = [{"id":"salary", "date":"2026-08-01", "description":"TEST FIXTURE salary", "amount":"80000", "type":"income"},
            {"id":"rent", "date":"2026-08-02", "description":"TEST FIXTURE rent", "amount":"20000", "type":"expense", "category":"housing"}]
    assert first.post(base + "/transactions", json={"transactions":rows}).status_code == 200
    first.post("/api/v1/agents/expense-analysis/run", json={"profile_id":alice["profile_id"]})
    selection = {"transaction_ids":["rent"], "deleted":True}
    assert second.post(base + "/transactions/selection", json=selection).status_code == 404
    assert first.post(base + "/transactions/selection", json=selection).json()["data"]["updated"] == 1
    assert [row["id"] for row in first.get(base + "/transactions").json()["data"]["transactions"]] == ["salary"]
    assert first.get(base + "/expense-analyses/latest").json()["data"]["is_current"] is False
    assert first.post(base + "/transactions/selection", json={**selection,"deleted":False}).status_code == 200
    assert len(first.get(base + "/transactions").json()["data"]["transactions"]) == 2
    # A missing ID fails atomically, without deleting the valid selection.
    assert first.post(base + "/transactions/selection", json={"transaction_ids":["rent","missing"]}).status_code == 404
    assert len(first.get(base + "/transactions").json()["data"]["transactions"]) == 2
