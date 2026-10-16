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


def test_transient_failure_uses_real_fallback_and_auth_errors_do_not():
    import asyncio
    import pytest
    from finagent.llm import _ResilientModel
    class Failure(Exception):
        def __init__(self,code): self.code=code
    class Model:
        def __init__(self,error=None): self.error=error; self.calls=0
        def with_structured_output(self,schema,**kwargs): return self
        def invoke(self,*args,**kwargs):
            self.calls+=1
            if self.error: raise self.error
            return {"answer":"TEST FIXTURE real secondary response"}
        async def ainvoke(self,*args,**kwargs): return self.invoke(*args,**kwargs)
    secondary=Model()
    model=_ResilientModel(Model(Failure(503)),lambda:secondary).with_structured_output(dict)
    assert model.invoke("question")["answer"].endswith("response")
    assert asyncio.run(model.ainvoke("question"))["answer"].endswith("response")
    assert secondary.calls==2
    with pytest.raises(Failure): _ResilientModel(Model(Failure(403)),lambda:secondary).invoke("question")
    assert secondary.calls==2
