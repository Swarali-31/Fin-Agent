"""Environment-backed settings for FinAgent."""

from __future__ import annotations

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / `.env`.

    Missing API keys do not fail at import; components that need them should
    call ``require_*`` helpers or validate at use time.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str | None = Field(default=None, alias="LLM_PROVIDER")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_fallback_model: str | None = Field(default=None, alias="LLM_FALLBACK_MODEL")
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")

    search_provider: str = Field(default="tavily", alias="SEARCH_PROVIDER")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    search_max_results: int = Field(default=5, alias="SEARCH_MAX_RESULTS")
    search_timeout_seconds: float = Field(default=30.0, alias="SEARCH_TIMEOUT_SECONDS")

    official_domains_raw: str = Field(default="", alias="OFFICIAL_DOMAINS")

    @field_validator("official_domains_raw", mode="before")
    @classmethod
    def _coerce_official_domains(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    @property
    def official_domains(self) -> list[str]:
        """Official domains as a trimmed, non-empty list."""
        if not self.official_domains_raw.strip():
            return []
        return [part.strip() for part in self.official_domains_raw.split(",") if part.strip()]

    def require_llm_config(self) -> tuple[str, str]:
        """Return ``(provider, model)`` or raise with a clear message."""
        if not self.llm_provider or not self.llm_provider.strip():
            raise ValueError(
                "LLM_PROVIDER is not set. Configure it in the environment or .env before using the LLM."
            )
        if not self.llm_model or not self.llm_model.strip():
            raise ValueError(
                "LLM_MODEL is not set. Configure it in the environment or .env before using the LLM."
            )
        return self.llm_provider.strip(), self.llm_model.strip()

    def require_api_key_for_provider(self, provider: str) -> str:
        """Return the API key for ``provider`` or raise with a clear message."""
        normalized = provider.lower().strip()
        key_map = {
            "anthropic": self.anthropic_api_key,
            "openai": self.openai_api_key,
            "google_genai": self.google_api_key,
            "google": self.google_api_key,
        }
        key = key_map.get(normalized)
        if not key or not str(key).strip():
            raise ValueError(
                f"API key for LLM provider '{provider}' is not set. "
                f"Set the appropriate environment variable before using the LLM."
            )
        return str(key).strip()

    def require_tavily_api_key(self) -> str:
        """Return Tavily API key or raise with a clear message."""
        if not self.tavily_api_key or not str(self.tavily_api_key).strip():
            raise ValueError(
                "TAVILY_API_KEY is not set. Configure it before using web search."
            )
        return str(self.tavily_api_key).strip()


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance (safe to call at import time)."""
    return Settings()
