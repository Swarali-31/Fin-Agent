"""Optional environment-backed backend settings."""

from __future__ import annotations

import json
from urllib.parse import quote
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Backend settings; optional integrations do not block application startup."""

    model_config = SettingsConfigDict(
        env_file=(_BACKEND_ROOT.parent / ".env", _BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        alias="CORS_ORIGINS",
    )
    database_url: str | None = Field(default=None, alias="DATABASE_URL", repr=False, exclude=True)
    supabase_db_host: str | None = Field(default=None, alias="SUPABASE_DB_HOST")
    supabase_db_user: str | None = Field(default=None, alias="SUPABASE_DB_USER")
    supabase_db_password: SecretStr | None = Field(default=None, alias="SUPABASE_DB_PASSWORD", repr=False, exclude=True)
    secure_cookies: bool = Field(default=False, alias="SECURE_COOKIES")
    max_steps: int = Field(default=8, ge=1, alias="MAX_STEPS")
    max_retries_per_step: int = Field(default=2, ge=0, alias="MAX_RETRIES_PER_STEP")
    max_replans: int = Field(default=2, ge=0, alias="MAX_REPLANS")
    retry_backoff_seconds: float = Field(default=0.5, ge=0, alias="RETRY_BACKOFF_SECONDS")

    llm_provider: str | None = Field(default=None, alias="LLM_PROVIDER")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")
    llm_fallback_model: str | None = Field(default=None, alias="LLM_FALLBACK_MODEL")
    llm_temperature: float = Field(default=0, alias="LLM_TEMPERATURE")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")

    search_provider: str = Field(default="tavily", alias="SEARCH_PROVIDER")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    search_max_results: int = Field(default=5, ge=1, alias="SEARCH_MAX_RESULTS")
    search_timeout_seconds: float = Field(default=30, gt=0, alias="SEARCH_TIMEOUT_SECONDS")
    official_domains: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        alias="OFFICIAL_DOMAINS",
    )

    @model_validator(mode="after")
    def supabase_connection(self):
        if not self.database_url and self.supabase_db_host and self.supabase_db_user and self.supabase_db_password:
            password = self.supabase_db_password.get_secret_value()
            if password:
                self.database_url = (f"postgresql+psycopg://{quote(self.supabase_db_user, safe='')}:{quote(password, safe='')}"
                                     f"@{self.supabase_db_host}:5432/postgres?sslmode=require")
        return self

    @field_validator("cors_origins", "official_domains", mode="before")
    @classmethod
    def _split_csv_values(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value

    @field_validator(
        "database_url",
        "llm_provider",
        "llm_model",
        "anthropic_api_key",
        "openai_api_key",
        "google_api_key",
        "tavily_api_key",
        mode="before",
    )
    @classmethod
    def _empty_string_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings without requiring optional configuration."""
    return Settings()
