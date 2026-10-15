from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_response_envelope_and_request_id() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "test-request-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert response.json() == {
        "request_id": "test-request-123",
        "status": "ok",
        "data": {"status": "ok"},
        "warnings": [],
        "error": None,
    }
