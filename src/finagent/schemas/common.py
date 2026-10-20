"""Shared primitives and agent result base types."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

_TWO_PLACES = Decimal("0.01")
_MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _decimal_from_input(value: object, *, signed: bool) -> Decimal:
    if isinstance(value, float):
        raise ValueError("float amounts are not allowed; use int, str, or Decimal")
    if isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, Decimal):
        dec = value
    elif isinstance(value, str):
        dec = Decimal(value.strip())
    else:
        raise TypeError(f"unsupported amount type: {type(value)!r}")

    dec = _quantize_money(dec)
    if not signed and dec < 0:
        raise ValueError("amount must be non-negative")
    return dec


class Money(BaseModel):
    """Non-negative monetary amount (2 decimal places, half-up rounding)."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(..., description="Quantity in profile currency")

    @field_validator("amount", mode="before")
    @classmethod
    def _validate_amount(cls, value: object) -> Decimal:
        return _decimal_from_input(value, signed=False)

    @field_serializer("amount", when_used="json")
    def _serialize_amount(self, value: Decimal) -> str:
        return str(_quantize_money(value))

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Money):
            return self.amount > other.amount
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Money):
            return self.amount >= other.amount
        return NotImplemented


class SignedMoney(BaseModel):
    """Signed monetary amount (surplus, shortfall, deltas)."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(..., description="Signed quantity in profile currency")

    @field_validator("amount", mode="before")
    @classmethod
    def _validate_amount(cls, value: object) -> Decimal:
        return _decimal_from_input(value, signed=True)

    @field_serializer("amount", when_used="json")
    def _serialize_amount(self, value: Decimal) -> str:
        return str(_quantize_money(value))


CurrencyCode = str
Month = str


def validate_currency_code(value: str) -> str:
    """Three-letter uppercase ISO-like currency code."""
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be exactly 3 uppercase letters")
    return value


def validate_month(value: str) -> str:
    """Calendar month in ``YYYY-MM`` form."""
    if not _MONTH_PATTERN.fullmatch(value):
        raise ValueError("month must be YYYY-MM")
    year, month = value.split("-")
    m = int(month)
    if m < 1 or m > 12:
        raise ValueError("month must be between 01 and 12")
    return value


class ExpenseCategory(str, Enum):
    housing = "housing"
    groceries = "groceries"
    utilities = "utilities"
    transport = "transport"
    dining = "dining"
    entertainment = "entertainment"
    healthcare = "healthcare"
    education = "education"
    insurance = "insurance"
    debt_payment = "debt_payment"
    subscriptions = "subscriptions"
    shopping = "shopping"
    travel = "travel"
    other = "other"


class TransactionType(str, Enum):
    income = "income"
    expense = "expense"
    refund = "refund"
    transfer = "transfer"


class AgentName(str, Enum):
    expense_analysis = "expense_analysis"
    budget_planning = "budget_planning"
    financial_research = "financial_research"
    financial_report = "financial_report"


class AgentStatus(str, Enum):
    success = "success"
    partial = "partial"
    failed = "failed"


class ValidationStatus(str, Enum):
    valid = "valid"
    flagged = "flagged"
    rejected = "rejected"


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


class SourceTier(str, Enum):
    official = "official"
    reputable = "reputable"
    other = "other"


class AgentError(BaseModel):
    """Structured agent failure (expected errors are returned, not raised)."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    recoverable: bool = False
    details: dict[str, Any] | None = None


class Limitation(BaseModel):
    """Non-fatal capability or data limitation."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class AgentResultBase(BaseModel):
    """Common envelope for agent outputs."""

    model_config = ConfigDict(extra="forbid")

    agent: AgentName
    status: AgentStatus
    errors: list[AgentError] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _json_default(obj: object) -> object:
    if isinstance(obj, Decimal):
        return str(_quantize_money(obj))
    raise TypeError(f"Object of type {type(obj)!r} is not JSON serializable")


def compute_version(prefix: str, payload: dict[str, Any]) -> str:
    """Deterministic version id: ``{prefix}-{first 12 hex chars of sha256}``.

    Payload is serialized as canonical JSON (sorted keys, Decimals as strings).
    Timestamps and other non-JSON types must not appear in ``payload``.
    """
    canonical = json.dumps(payload, sort_keys=True, default=_json_default, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
