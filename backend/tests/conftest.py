"""Isolate process-local account rate limits between test cases."""
import pytest
from backend.app.auth.routes import _attempts


@pytest.fixture(autouse=True)
def reset_account_attempts():
    _attempts.clear()
    yield
    _attempts.clear()
