"""File provenance survives analysis and sessions without exposing other accounts."""
import pytest
from pydantic import ValidationError
from backend.app.auth.routes import Credentials
from backend.tests.test_auth_workspace import accounts, register


@pytest.mark.parametrize("email", [None, 123, "bad", "alice@example", ".alice@example.com", "alice..smith@example.com", "alice@-example.com", "alice@example..com"])
def test_invalid_email_rejected_on_server(email):
    with pytest.raises(ValidationError):
        Credentials(email=email, password="test-password")


def test_email_normalized_before_validation():
    assert Credentials(email=" Alice+test@Example.COM ", password="test-password").email == "alice+test@example.com"


def test_file_history_survives_analysis_and_login(accounts):
    first, second = accounts
    alice = register(first, "files-alice@example.invalid")
    register(second, "files-bob@example.invalid")
    path = f"/api/v1/profiles/{alice['profile_id']}/transactions"
    rows = [{"id": "salary", "date": "2026-10-01", "description": "DEMO salary", "amount": "1000.00", "type": "income"},
            {"id": "food", "date": "2026-10-02", "description": "DEMO groceries", "amount": "100.00", "type": "expense", "category": "groceries"}]
    payload = {"transactions": rows, "import_metadata": {"filename": "October.csv", "format": "csv"}}
    assert first.post(path, json=payload).status_code == 200
    assert second.get(path).status_code == 404
    assert second.post(path, json=payload).status_code == 404
    assert first.post("/api/v1/agents/expense-analysis/run", json={"profile_id": alice["profile_id"]}).status_code == 200
    result = first.get(path).json()["data"]
    batch = result["imports"][0]
    assert batch["filename"] == "October.csv"
    assert batch["transaction_count"] == 2
    assert batch["transaction_ids"] == ["salary", "food"]
    assert batch["period_start"] == "2026-10-01"
    # A rejected duplicate batch must not add a file-history entry.
    assert first.post(path, json=payload).status_code == 409
    assert first.post(path, json={"transactions": [{**rows[1], "id": "new"}], "import_metadata": {"filename": "../bad.csv", "format": "csv"}}).status_code == 422
    assert len(first.get(path).json()["data"]["imports"]) == 1
    assert first.post("/api/v1/auth/logout").status_code == 200
    assert first.post("/api/v1/auth/login", json={"email": alice["email"], "password": "test-only-password"}).status_code == 200
    assert first.get(path).json()["data"]["imports"] == [batch]
    # A second file and a soft deletion preserve the original history.
    assert first.post(path, json={"transactions": [{**rows[1], "id": "second-food"}], "import_metadata": {"filename": "More.json", "format": "json"}}).status_code == 200
    assert first.post(path + "/selection", json={"transaction_ids": ["food"], "deleted": True}).status_code == 200
    result = first.get(path).json()["data"]
    assert [item["filename"] for item in result["imports"]] == ["More.json", "October.csv"]
    assert [item["id"] for item in result["transactions"]] == ["salary", "second-food"]
