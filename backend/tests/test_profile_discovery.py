"""Profile discovery must make previously saved data easy to find at login."""
from backend.tests.test_auth_workspace import accounts, register


def test_login_prefers_populated_profiles_and_counts_are_account_scoped(accounts):
    first, second = accounts
    alice = register(first,"discover-alice@example.invalid")
    bob = register(second,"discover-bob@example.invalid")
    assert first.post("/api/v1/profiles",json={"profile_id":"history","currency":"INR"}).status_code == 201
    assert first.post("/api/v1/profiles/history/transactions",json={"transactions":[
        {"id":"food","date":"2026-10-01","description":"TEST food","amount":"100.00","type":"expense"},
    ],"import_metadata":{"filename":"history.csv","format":"csv"}}).status_code == 200
    assert first.post("/api/v1/profiles",json={"profile_id":"new-empty","currency":"INR"}).status_code == 201
    profiles = first.get("/api/v1/profiles").json()["data"]
    assert profiles[0]["profile_id"] == "history"
    assert profiles[0]["transaction_count"] == 1 and profiles[0]["file_count"] == 1
    assert all(item["transaction_count"] == 0 for item in profiles[1:])
    assert [item["profile_id"] for item in second.get("/api/v1/profiles").json()["data"]] == [bob["profile_id"]]
    assert first.post("/api/v1/auth/logout").status_code == 200
    response = first.post("/api/v1/auth/login",json={"email":alice["email"],"password":"test-only-password"})
    assert response.json()["data"]["profile_id"] == "history"
    assert first.post("/api/v1/profiles/history/transactions/selection",json={"transaction_ids":["food"],"deleted":True}).status_code == 200
    profile = first.get("/api/v1/profiles").json()["data"][0]
    assert profile["profile_id"] == "history"
    assert profile["transaction_count"] == 0 and profile["file_count"] == 1
    assert profile["deleted_count"] == 1
    saved = first.get("/api/v1/profiles/history/transactions").json()["data"]
    assert saved["transactions"] == []
    assert [item["id"] for item in saved["deleted_transactions"]] == ["food"]
    assert "_finagent_deleted" not in saved["deleted_transactions"][0]
    assert second.get("/api/v1/profiles/history/transactions").status_code == 404
    # Persistent recovery works across a new session, not just the temporary Undo button.
    first.post("/api/v1/auth/logout")
    assert first.post("/api/v1/auth/login",json={"email":alice["email"],"password":"test-only-password"}).status_code == 200
    assert first.post("/api/v1/profiles/history/transactions/selection",json={"transaction_ids":["food"],"deleted":False}).status_code == 200
    restored = first.get("/api/v1/profiles/history/transactions").json()["data"]
    assert len(restored["transactions"]) == 1 and restored["deleted_transactions"] == []
