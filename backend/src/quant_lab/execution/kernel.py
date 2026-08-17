from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from quant_lab.backtest.rules import (
    BacktestRuleError,
    FeePolicy,
    InstrumentSpec,
    SlippagePolicy,
    apply_slippage,
    calculate_fees,
    round_lot,
    validate_execution_price,
)


class ExecutionStatus(StrEnum):
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    instrument_id: str
    side: str
    requested_quantity: int
    order_type: str
    limit_price: Decimal | None
    execution_date: date
    cash: Decimal
    sellable_quantity: int
    instrument: InstrumentSpec
    bar: dict[str, object] | None
    fee_policy: FeePolicy
    slippage_policy: SlippagePolicy
    max_volume_participation: Decimal | None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    requested_quantity: int
    accepted_quantity: int
    filled_quantity: int
    remaining_quantity: int
    raw_price: Decimal | None
    slippage: Decimal
    fill_price: Decimal | None
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal
    cash_delta: Decimal
    reject_reason: str | None


def _rejected(request: ExecutionRequest, reason: str) -> ExecutionResult:
    return ExecutionResult(
        status=ExecutionStatus.REJECTED.value,
        requested_quantity=request.requested_quantity,
        accepted_quantity=0,
        filled_quantity=0,
        remaining_quantity=request.requested_quantity,
        raw_price=None,
        slippage=Decimal("0"),
        fill_price=None,
        commission=Decimal("0"),
        stamp_tax=Decimal("0"),
        transfer_fee=Decimal("0"),
        total_fee=Decimal("0"),
        cash_delta=Decimal("0"),
        reject_reason=reason,
    )


class ExecutionKernel:
    """Pure, deterministic single-order market execution.

    No DB, HTTP, filesystem, MarketDataService, strategy, RiskEngine, or
    session-advance access. It answers exactly how one order executes against a
    known bar, given explicit cash/sellable/policy inputs.
    """

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.bar is None or request.bar.get("open") is None:
            return ExecutionResult(
                status=ExecutionStatus.EXPIRED.value,
                requested_quantity=request.requested_quantity,
                accepted_quantity=0,
                filled_quantity=0,
                remaining_quantity=request.requested_quantity,
                raw_price=None,
                slippage=Decimal("0"),
                fill_price=None,
                commission=Decimal("0"),
                stamp_tax=Decimal("0"),
                transfer_fee=Decimal("0"),
                total_fee=Decimal("0"),
                cash_delta=Decimal("0"),
                reject_reason="BAR_MISSING",
            )

        requested = request.requested_quantity
        quantity = requested
        if request.side == "SELL" and quantity > request.sellable_quantity:
            return _rejected(request, "T1_SELL_RESTRICTED")

        if request.max_volume_participation is not None:
            volume = request.bar.get("volume")
            if volume is None or Decimal(str(volume)) <= 0:
                return _rejected(request, "VOLUME_UNAVAILABLE")
            max_raw = int(Decimal(str(volume)) * request.max_volume_participation)
            volume_limited = round_lot(max_raw, request.instrument.lot_size)
            if volume_limited < request.instrument.lot_size:
                return _rejected(request, "VOLUME_TOO_LOW")
            quantity = min(quantity, volume_limited)

        raw = Decimal(str(request.bar["open"]))
        try:
            validate_execution_price(
                raw,
                limit_up=_decimal_or_none(request.bar.get("limit_up")),
                limit_down=_decimal_or_none(request.bar.get("limit_down")),
                side=request.side,
            )
            fill_price, slippage = apply_slippage(
                raw, request.slippage_policy, side=request.side, tick=request.instrument.price_tick
            )
            commission, stamp, transfer, total = calculate_fees(
                security_type=request.instrument.security_type,
                side=request.side,
                quantity=quantity,
                price=fill_price,
                policy=request.fee_policy,
            )
            if request.side == "BUY" and quantity * fill_price + total > request.cash:
                raise BacktestRuleError("INSUFFICIENT_CASH", "现金不足")
        except BacktestRuleError as error:
            return _rejected(request, error.code)

        status = (
            ExecutionStatus.PARTIALLY_FILLED.value
            if quantity < requested
            else ExecutionStatus.FILLED.value
        )
        cash_delta = (
            -(quantity * fill_price + total)
            if request.side == "BUY"
            else quantity * fill_price - total
        )
        return ExecutionResult(
            status=status,
            requested_quantity=requested,
            accepted_quantity=quantity,
            filled_quantity=quantity,
            remaining_quantity=requested - quantity,
            raw_price=raw,
            slippage=slippage,
            fill_price=fill_price,
            commission=commission,
            stamp_tax=stamp,
            transfer_fee=transfer,
            total_fee=total,
            cash_delta=cash_delta,
            reject_reason=None,
        )


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))
