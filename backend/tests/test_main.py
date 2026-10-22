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


def test_unsupported_health_method_preserves_http_status_and_allow_header() -> None:
    client = TestClient(app)

    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert "GET" in response.headers["Allow"]
    assert response.json()["error"]["code"] == "http_error"
