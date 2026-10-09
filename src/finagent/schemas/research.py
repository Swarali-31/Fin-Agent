"""Financial research agent I/O models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from finagent.schemas.common import AgentName, AgentResultBase, SourceTier


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    jurisdiction: str = "IN"
    max_sources: int = Field(default=5, ge=1, le=10)
    preferred_domains: list[str] | None = None


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., pattern=r"^S\d+$")
    title: str
    url: HttpUrl
    publisher: str | None = None
    published_date: date | None = None
    retrieved_at: datetime
    tier: SourceTier
    snippet: str | None = None


class ResearchFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    source_ids: list[str] = Field(..., min_length=1)
    confidence: Literal["low", "medium", "high"]


class ResearchResult(AgentResultBase):
    model_config = ConfigDict(extra="forbid")

    agent: AgentName = AgentName.financial_research
    question: str
    findings: list[ResearchFinding] = Field(default_factory=list)
    sources: list[SourceMetadata] = Field(default_factory=list)
    search_provider: str | None = None
    disclaimer: str = Field(
        default="Educational information only; not personalized financial advice."
    )

    @model_validator(mode="after")
    def _source_ids_exist(self) -> ResearchResult:
        known = {s.source_id for s in self.sources}
        for finding in self.findings:
            missing = [sid for sid in finding.source_ids if sid not in known]
            if missing:
                raise ValueError(f"finding references unknown source_ids: {missing}")
        return self
