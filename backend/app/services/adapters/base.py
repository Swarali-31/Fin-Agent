"""Shared adapter contract and result normalization."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

from fastapi.encoders import jsonable_encoder
from finagent.config import Settings as FinAgentSettings
from finagent.llm import get_llm
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from backend.app.config.settings import Settings
from backend.app.schemas.common import (
    AdapterStatus,
    AgentEnvelope,
    AgentProvenance,
)

Context = Mapping[str, Any] | None
ResultModel = TypeVar("ResultModel", bound=BaseModel)

_API_KEY_ENV_BY_PROVIDER = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "google": ("GOOGLE_API_KEY", "google_api_key"),
    "google_genai": ("GOOGLE_API_KEY", "google_api_key"),
}


@runtime_checkable
class AgentAdapter(Protocol):
    """Async backend boundary around a synchronous FinAgent runner."""

    name: str

    def capabilities(self) -> list[str]: ...

    def status(self) -> AdapterStatus: ...

    async def run(self, input: Any, context: Context = None) -> AgentEnvelope: ...


class AdapterConfigurationError(RuntimeError):
    """Required agent configuration is absent or invalid."""


class AgentAdapterBase:
    """Common input hashing, dependency injection, and response conversion."""

    name = "agent"
    capabilities_list: tuple[str, ...] = ()

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def capabilities(self) -> list[str]:
        return list(self.capabilities_list)

    def status(self) -> AdapterStatus:
        missing = self.missing_llm_configuration()
        if not missing:
            return AdapterStatus(status="available")
        if self.settings.llm_provider and self.settings.llm_model:
            return AdapterStatus(status="misconfigured", missing=missing)
        return AdapterStatus(status="partial", missing=missing)

    def missing_llm_configuration(self) -> list[str]:
        missing: list[str] = []
        provider = (self.settings.llm_provider or "").strip().lower()
        if not provider:
            missing.append("LLM_PROVIDER")
        if not (self.settings.llm_model or "").strip():
            missing.append("LLM_MODEL")
        if provider:
            key_info = _API_KEY_ENV_BY_PROVIDER.get(provider)
            if key_info is None:
                missing.append("LLM_PROVIDER (unsupported)")
            elif not (getattr(self.settings, key_info[1]) or "").strip():
                missing.append(key_info[0])
        return missing

    def resolve_llm(self, context: Context) -> Any:
        if context is not None and "llm" in context:
            return context["llm"]
        if not self.settings.llm_provider or not self.settings.llm_model:
            return False
        missing = self.missing_llm_configuration()
        if missing:
            raise AdapterConfigurationError(
                "LLM configuration is incomplete: " + ", ".join(missing)
            )
        finagent_settings = FinAgentSettings(
            LLM_PROVIDER=self.settings.llm_provider,
            LLM_MODEL=self.settings.llm_model,
            LLM_TEMPERATURE=self.settings.llm_temperature,
            ANTHROPIC_API_KEY=self.settings.anthropic_api_key,
            OPENAI_API_KEY=self.settings.openai_api_key,
            GOOGLE_API_KEY=self.settings.google_api_key,
            SEARCH_PROVIDER=self.settings.search_provider,
            TAVILY_API_KEY=self.settings.tavily_api_key,
            SEARCH_MAX_RESULTS=self.settings.search_max_results,
            SEARCH_TIMEOUT_SECONDS=self.settings.search_timeout_seconds,
            OFFICIAL_DOMAINS=",".join(self.settings.official_domains),
        )
        try:
            return get_llm(settings=finagent_settings)
        except (ImportError, ValueError) as exc:
            raise AdapterConfigurationError(str(exc)) from exc

    async def invoke(
        self,
        *,
        input_value: Any,
        operation: Callable[[], ResultModel],
        started_at: datetime,
        started_counter: float,
    ) -> AgentEnvelope:
        try:
            result = await run_in_threadpool(operation)
            return self.envelope(
                input_value=input_value,
                result=result,
                started_at=started_at,
                started_counter=started_counter,
            )
        except Exception as exc:
            return self.failed_envelope(
                input_value=input_value,
                started_at=started_at,
                started_counter=started_counter,
                code="adapter_execution_error",
                message="The agent adapter could not complete the request.",
                details={"exception_type": type(exc).__name__},
            )

    def envelope(
        self,
        *,
        input_value: Any,
        result: BaseModel,
        started_at: datetime,
        started_counter: float,
    ) -> AgentEnvelope:
        payload = result.model_dump(mode="json")
        result_status = payload.get("status")
        if hasattr(result_status, "value"):
            result_status = result_status.value
        if result_status not in {"success", "partial", "failed"}:
            result_status = "failed"
        return AgentEnvelope(
            agent=self.name,
            status=result_status,
            result=payload,
            errors=payload.get("errors", []),
            limitations=payload.get("limitations", []),
            provenance=self.provenance(
                input_value=input_value,
                result_payload=payload,
                started_at=started_at,
                started_counter=started_counter,
            ),
        )

    def failed_envelope(
        self,
        *,
        input_value: Any,
        started_at: datetime,
        started_counter: float,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> AgentEnvelope:
        error = {"code": code, "message": message}
        if details:
            error["details"] = details
        return AgentEnvelope(
            agent=self.name,
            status="failed",
            errors=[error],
            provenance=self.provenance(
                input_value=input_value,
                result_payload={},
                started_at=started_at,
                started_counter=started_counter,
            ),
        )

    def validation_failure(
        self,
        *,
        input_value: Any,
        error: ValidationError,
        started_at: datetime,
        started_counter: float,
    ) -> AgentEnvelope:
        return self.failed_envelope(
            input_value=input_value,
            started_at=started_at,
            started_counter=started_counter,
            code="invalid_input",
            message="The input does not match the agent request schema.",
            details={
                "validation_errors": [
                    {
                        "location": ".".join(str(part) for part in issue["loc"]),
                        "message": issue["msg"],
                        "type": issue["type"],
                    }
                    for issue in error.errors()
                ]
            },
        )

    def provenance(
        self,
        *,
        input_value: Any,
        result_payload: dict[str, Any],
        started_at: datetime,
        started_counter: float,
    ) -> AgentProvenance:
        source_versions = result_payload.get("source_versions") or {}
        return AgentProvenance(
            agent=self.name,
            analysis_version=result_payload.get("analysis_version")
            or source_versions.get("analysis_version"),
            budget_id=result_payload.get("budget_id")
            or source_versions.get("budget_id"),
            budget_revision=result_payload.get("revision")
            or source_versions.get("budget_revision"),
            source_analysis_version=result_payload.get("source_analysis_version"),
            report_version=result_payload.get("report_version"),
            input_hash=_input_hash(input_value),
            started_at=started_at,
            duration_ms=max(0, round((time.perf_counter() - started_counter) * 1000)),
        )


def begin_timing() -> tuple[datetime, float]:
    return datetime.now(UTC), time.perf_counter()


def _input_hash(value: Any) -> str:
    encoded = jsonable_encoder(value)
    canonical = json.dumps(encoded, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
