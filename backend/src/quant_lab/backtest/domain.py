from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum


class BacktestRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    LIMIT = "LIMIT"
    MARKET_ON_OPEN_SIMULATED = "MARKET_ON_OPEN_SIMULATED"


class SimulatedOrderStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    client_order_id: str
    instrument_id: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    signal_date: date
    intended_execution_date: date
    strategy_reason: str
    strategy_metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class SimulatedOrder:
    order_id: str
    client_order_id: str
    instrument_id: str
    side: OrderSide
    requested_quantity: int
    accepted_quantity: int
    filled_quantity: int
    limit_price: Decimal | None
    status: SimulatedOrderStatus
    submitted_date: date
    execution_date: date | None
    reject_reason: str | None


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    fill_id: str
    order_id: str
    instrument_id: str
    side: OrderSide
    quantity: int
    raw_price: Decimal
    slippage: Decimal
    fill_price: Decimal
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal
    trade_date: date


@dataclass(frozen=True, slots=True)
class PositionLot:
    instrument_id: str
    acquired_date: date
    quantity: int
    remaining_quantity: int
    cost_price: Decimal
    sellable_from_date: date


@dataclass(frozen=True, slots=True)
class EquityPoint:
    trade_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    stale_valuation: bool
