from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class RiskReasonCode(StrEnum):
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN"
    SESSION_NOT_RUNNING = "SESSION_NOT_RUNNING"
    SECURITY_NOT_ALLOWED = "SECURITY_NOT_ALLOWED"
    ORDER_NOTIONAL_LIMIT = "ORDER_NOTIONAL_LIMIT"
    CASH_BUFFER_LIMIT = "CASH_BUFFER_LIMIT"
    POSITION_CONCENTRATION_LIMIT = "POSITION_CONCENTRATION_LIMIT"
    TOTAL_EXPOSURE_LIMIT = "TOTAL_EXPOSURE_LIMIT"
    OPEN_ORDER_LIMIT = "OPEN_ORDER_LIMIT"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    RISK_ENGINE_ERROR = "RISK_ENGINE_ERROR"
    RISK_CONTEXT_INVALID = "RISK_CONTEXT_INVALID"


RISK_REASON_ORDER: tuple[str, ...] = (
    RiskReasonCode.ACCOUNT_FROZEN.value,
    RiskReasonCode.SESSION_NOT_RUNNING.value,
    RiskReasonCode.SECURITY_NOT_ALLOWED.value,
    RiskReasonCode.ORDER_NOTIONAL_LIMIT.value,
    RiskReasonCode.CASH_BUFFER_LIMIT.value,
    RiskReasonCode.POSITION_CONCENTRATION_LIMIT.value,
    RiskReasonCode.TOTAL_EXPOSURE_LIMIT.value,
    RiskReasonCode.OPEN_ORDER_LIMIT.value,
    RiskReasonCode.DAILY_LOSS_LIMIT.value,
    RiskReasonCode.DRAWDOWN_LIMIT.value,
)


@dataclass(frozen=True, slots=True)
class RiskAccountSnapshot:
    account_id: str
    status: str
    cash: Decimal
    market_value: Decimal
    account_equity: Decimal
    gross_exposure: Decimal
    daily_loss_ratio: Decimal
    drawdown_ratio: Decimal


@dataclass(frozen=True, slots=True)
class RiskPositionSnapshot:
    instrument_id: str
    total_quantity: int
    sellable_quantity: int
    market_value: Decimal


@dataclass(frozen=True, slots=True)
class RiskMarketContext:
    instrument_id: str
    security_type: str
    reference_price: Decimal
    estimated_fee: Decimal
    session_date: date


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    decision: str
    reason_codes: tuple[str, ...]
    policy_fingerprint: str
    evaluated_metrics: dict[str, object]
    freeze_required: bool


@dataclass(frozen=True, slots=True)
class RiskPolicyView:
    policy_id: str
    version_id: str
    version: int
    fingerprint: str
    max_single_order_notional: Decimal
    max_single_position_weight: Decimal
    max_total_exposure: Decimal
    cash_buffer_ratio: Decimal
    max_daily_loss: Decimal
    max_drawdown: Decimal
    max_open_orders: int
    allowed_security_types: frozenset[str]
