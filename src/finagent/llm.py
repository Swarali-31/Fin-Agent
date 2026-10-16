"""LLM factory for FinAgent (single provider/model for all agents)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from finagent.config import Settings


_PROVIDER_PACKAGE: dict[str, str] = {
    "anthropic": "langchain_anthropic",
    "openai": "langchain_openai",
    "google_genai": "langchain_google_genai",
    "google": "langchain_google_genai",
}


def get_llm(settings: Settings | None = None, **kwargs: Any) -> BaseChatModel:
    """Build a chat model from ``Settings`` using LangChain's ``init_chat_model``.

    Parameters
    ----------
    settings:
        Optional settings; defaults to cached ``get_settings()``.
    **kwargs:
        Passed through to ``init_chat_model`` (e.g. for tests).

    Raises
    ------
    ValueError
        If provider, model, package, or API key is missing.
    ImportError
        If the optional provider package is not installed.
    """
    from finagent.config import Settings, get_settings

    cfg = settings or get_settings()
    provider, model = cfg.require_llm_config()
    provider = provider.strip().lower()
    if provider == "google":
        provider = "google_genai"
    api_key = cfg.require_api_key_for_provider(provider)

    package = _PROVIDER_PACKAGE.get(provider.lower())
    if package is None:
        raise ValueError(
            f"Unsupported LLM_PROVIDER '{provider}'. "
            f"Supported: {', '.join(sorted(set(_PROVIDER_PACKAGE.keys())))}."
        )
    try:
        __import__(package)
    except ImportError as exc:
        raise ImportError(
            f"Optional dependency for provider '{provider}' is not installed. "
            f"Install the matching extra (e.g. pip install finagent[{provider}])."
        ) from exc

    from langchain.chat_models import init_chat_model

    init_kwargs: dict[str, Any] = {
        "model": model,
        "model_provider": provider.lower(),
        "temperature": cfg.llm_temperature,
        "timeout": 45,
        "max_retries": 1,
        **kwargs,
    }
    # LangChain providers use different env var names; pass key explicitly when possible.
    if provider.lower() in ("anthropic",):
        init_kwargs["api_key"] = api_key
    elif provider.lower() == "openai":
        init_kwargs["api_key"] = api_key
    elif provider.lower() in ("google", "google_genai"):
        init_kwargs["google_api_key"] = api_key

    primary = init_chat_model(**init_kwargs)
    fallback_name = cfg.llm_fallback_model
    if provider == "google_genai" and fallback_name and fallback_name != model:
        return _ResilientModel(primary, lambda: init_chat_model(**{**init_kwargs, "model": fallback_name, "max_retries": 0}))
    return primary


class _ResilientModel:
    """Use a real secondary model only for transient provider failures."""

    def __init__(self, primary, fallback_factory):
        self.primary = primary
        self.fallback_factory = fallback_factory

    @staticmethod
    def transient(error):
        code = getattr(error, "status_code", None) or getattr(error, "code", None)
        return isinstance(error, TimeoutError) or str(code) in {"429", "500", "502", "503", "504"}

    def with_structured_output(self, schema, **kwargs):
        return _ResilientModel(self.primary.with_structured_output(schema, **kwargs),
                               lambda: self.fallback_factory().with_structured_output(schema, **kwargs))

    def invoke(self, *args, **kwargs):
        try:
            return self.primary.invoke(*args, **kwargs)
        except Exception as error:
            if not self.transient(error):
                raise
            return self.fallback_factory().invoke(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        try:
            return await self.primary.ainvoke(*args, **kwargs)
        except Exception as error:
            if not self.transient(error):
                raise
            return await self.fallback_factory().ainvoke(*args, **kwargs)
