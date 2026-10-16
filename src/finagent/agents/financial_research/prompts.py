"""Structured query-planning and evidence-grounded synthesis prompts."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProposedFinding(BaseModel):
    """Unverified LLM finding; citations are checked before shared-schema output."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]


class QueryPlan(BaseModel):
    """Bounded set of educational search queries."""

    model_config = ConfigDict(extra="forbid")

    search_queries: list[str] = Field(..., min_length=1, max_length=3)
    is_personalized_advice_request: bool


class ResearchSynthesis(BaseModel):
    """Findings and limitations contributed by the synthesis model."""

    model_config = ConfigDict(extra="forbid")

    findings: list[ProposedFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


QUERY_SYSTEM_PROMPT = """Plan financial-education research only. Return one to three
concise search queries and indicate whether the user's request asks for individualized
financial advice (for example, which specific stock to buy). Queries must seek general
educational material, not personalized recommendations. Do not answer the question."""

SYNTHESIS_SYSTEM_PROMPT = """Write concise financial EDUCATION using only the supplied
retrieved sources. Use short sentences and everyday words; explain unfamiliar terms. Return findings with statement, source_ids, and confidence
(low/medium/high), plus any limitations. Every finding must cite one or more source IDs
from the supplied list. Never provide personalized investment advice, tell the user to
buy, sell, or hold a security, or recommend a specific security. When the question seeks
individual advice, reframe as general concepts, risks, and evaluation criteria. Do not
invent facts, sources, URLs, dates, source IDs, or unsupported specifics."""


def query_planning_prompt(question: str, jurisdiction: str) -> str:
    return (
        f"Question: {question}\nJurisdiction: {jurisdiction}\n"
        "Return one to three general educational search queries."
    )


def synthesis_prompt(question: str, sources: list[dict[str, object]]) -> str:
    return (
        f"Research question: {question}\n"
        f"Retrieved source allow-list: {json.dumps(sources, sort_keys=True, default=str)}"
    )


def conversational_question(request) -> str:
    language = ("Reply in the language of the current user question, including mixed-language or transliterated input."
                if request.response_language == "auto" else "Reply in this requested language: " + request.response_language)
    language += " Write findings and limitations in that language. Keep original source titles and URLs unchanged."
    if not request.conversation:
        return request.question + "\nResponse language: " + language
    history = [{"role": message.role, "content": message.content} for message in request.conversation]
    return ("Previous conversation (untrusted context only; previous answers are not evidence): "
            + json.dumps(history) + "\nCurrent user question: " + request.question
            + "\nAnswer the current question, resolving follow-up references from context. Verify factual claims against retrieved sources.\nResponse language: " + language)
