from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

from quant_lab.backtest.domain import OrderIntent, OrderSide, OrderType, PositionLot
from quant_lab.backtest.rules import (
    BacktestRuleError,
    FeePolicy,
    InstrumentSpec,
    validate_quantity,
    validate_sell_quantity,
)


@dataclass(frozen=True, slots=True)
class TargetPlan:
    sells: tuple[OrderIntent, ...]
    buys: tuple[OrderIntent, ...]
    unallocated_cash: Decimal
    reasons: tuple[str, ...]


def plan_target_weight(
    *,
    trade_date: date,
    execution_date: date,
    cash: Decimal,
    holdings: tuple[PositionLot, ...],
    equity: Decimal,
    instrument: InstrumentSpec,
    target_weight: Decimal,
    reference_price: Decimal,
    fee_policy: FeePolicy,
) -> TargetPlan:
    if equity <= 0 or cash < 0:
        raise BacktestRuleError("ACCOUNT_STATE_INVALID", "账户权益和现金状态无效")
    if not Decimal("0") <= target_weight <= Decimal("1"):
        raise BacktestRuleError("TARGET_WEIGHT_INVALID", "目标权重必须在0到1之间")
    current = sum(
        lot.remaining_quantity for lot in holdings if lot.instrument_id == instrument.instrument_id
    )
    target_quantity = round_lot_down(
        (equity * target_weight) / reference_price, instrument.lot_size
    )
    delta = target_quantity - current
    if delta == 0:
        return TargetPlan((), (), cash, ("TARGET_ALREADY_REACHED",))
    if delta < 0:
        sell_quantity = validate_sell_quantity(
            holdings, instrument.instrument_id, -delta, execution_date
        )
        return TargetPlan(
            sells=(
                OrderIntent(
                    str(uuid4()),
                    instrument.instrument_id,
                    OrderSide.SELL,
                    sell_quantity,
                    OrderType.MARKET_ON_OPEN_SIMULATED,
                    trade_date,
                    execution_date,
                    "TARGET_REBALANCE_SELL",
                    {},
                ),
            ),
            buys=(),
            unallocated_cash=cash,
            reasons=(),
        )
    buy_quantity = validate_quantity(delta, side="BUY", lot_size=instrument.lot_size)
    estimated = buy_quantity * reference_price
    _, _, _, total_fee = calculate_fees_for(instrument, buy_quantity, reference_price, fee_policy)
    if estimated + total_fee > cash:
        return TargetPlan((), (), cash, ("INSUFFICIENT_CASH",))
    return TargetPlan(
        sells=(),
        buys=(
            OrderIntent(
                str(uuid4()),
                instrument.instrument_id,
                OrderSide.BUY,
                buy_quantity,
                OrderType.MARKET_ON_OPEN_SIMULATED,
                trade_date,
                execution_date,
                "TARGET_REBALANCE_BUY",
                {},
            ),
        ),
        unallocated_cash=cash - estimated - total_fee,
        reasons=(),
    )


def round_lot_down(quantity: Decimal, lot_size: int) -> int:
    return int(quantity // lot_size) * lot_size


def calculate_fees_for(
    instrument: InstrumentSpec, quantity: int, price: Decimal, policy: FeePolicy
):
    from quant_lab.backtest.rules import calculate_fees

    return calculate_fees(
        security_type=instrument.security_type,
        side="BUY",
        quantity=quantity,
        price=price,
        policy=policy,
    )
