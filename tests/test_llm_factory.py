"""Provider selection checks without external model calls."""
import sys
from types import SimpleNamespace
from finagent.config import Settings
from finagent.llm import get_llm


def test_google_alias_uses_supported_langchain_provider(monkeypatch):
    captured = {}
    monkeypatch.setitem(sys.modules, "langchain_google_genai", SimpleNamespace())
    def fake_init(**kwargs):
        captured.update(kwargs)
        return "test-model"
    monkeypatch.setattr("langchain.chat_models.init_chat_model", fake_init)
    settings = Settings(LLM_PROVIDER="google", LLM_MODEL="test-model", GOOGLE_API_KEY="test-placeholder", _env_file=None)
    assert get_llm(settings) == "test-model"
    assert captured["model_provider"] == "google_genai"
    assert captured["google_api_key"] == "test-placeholder"
    assert captured["timeout"] == 45
