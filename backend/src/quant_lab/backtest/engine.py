from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import (
    EquityPoint,
    OrderIntent,
    OrderSide,
    PositionLot,
    SimulatedFill,
    SimulatedOrder,
    SimulatedOrderStatus,
)
from quant_lab.backtest.rules import (
    BacktestRuleError,
    FeePolicy,
    SlippagePolicy,
    apply_slippage,
    calculate_fees,
    round_lot,
    validate_execution_price,
    validate_sell_quantity,
)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    orders: tuple[SimulatedOrder, ...]
    fills: tuple[SimulatedFill, ...]
    positions: tuple[PositionLot, ...]
    equity_curve: tuple[EquityPoint, ...]
    final_cash: Decimal


class BacktestEngine:
    """Small deterministic daily event loop; it never infers weekdays as sessions."""

    def run(
        self,
        *,
        sessions: tuple[date, ...],
        bars_by_date: dict[date, dict[str, dict[str, object]]],
        strategy,
        initial_cash: Decimal,
        fee_policy: FeePolicy,
        slippage_policy: SlippagePolicy,
        max_volume_participation: Decimal | None = None,
    ) -> BacktestResult:
        if initial_cash <= 0:
            raise BacktestRuleError("INITIAL_CASH_INVALID", "初始资金必须大于0")
        ordered_sessions = tuple(sorted(sessions))
        cash = initial_cash
        lots: list[PositionLot] = []
        orders: list[SimulatedOrder] = []
        fills: list[SimulatedFill] = []
        equity_curve: list[EquityPoint] = []
        pending: list[OrderIntent] = []
        instruments = {spec.instrument_id: spec for spec in strategy.instruments}
        closes_history: dict[str, list[Decimal]] = {
            instrument_id: [] for instrument_id in instruments
        }
        last_valid_close: dict[str, Decimal] = {}
        for index, trade_date in enumerate(ordered_sessions):
            bars_today = bars_by_date.get(trade_date, {})
            next_date = ordered_sessions[index + 1] if index + 1 < len(ordered_sessions) else None
            for instrument_id, bar in bars_today.items():
                if bar.get("close") is not None:
                    close = Decimal(str(bar["close"]))
                    closes_history.setdefault(instrument_id, []).append(close)
                    last_valid_close[instrument_id] = close
            for intent in tuple(pending):
                pending.remove(intent)
                order, fill = self._execute(
                    intent,
                    trade_date,
                    bars_today.get(intent.instrument_id),
                    cash,
                    lots,
                    instruments[intent.instrument_id],
                    fee_policy,
                    slippage_policy,
                    max_volume_participation,
                )
                orders.append(order)
                if fill is not None:
                    fills.append(fill)
                    cash = (
                        cash - fill.quantity * fill.fill_price - fill.total_fee
                        if fill.side == OrderSide.BUY
                        else cash + fill.quantity * fill.fill_price - fill.total_fee
                    )
                    if fill.side == OrderSide.BUY:
                        lots.append(
                            PositionLot(
                                fill.instrument_id,
                                trade_date,
                                fill.quantity,
                                fill.quantity,
                                fill.fill_price,
                                next_date or trade_date,
                            )
                        )
            market_value, stale = self._market_value(lots, bars_today, last_valid_close)
            if bars_today:
                pending.extend(
                    strategy.on_close(
                        signal_date=trade_date,
                        execution_date=next_date,
                        bars=bars_today,
                        cash=cash,
                        equity=cash + market_value,
                        lots=tuple(lots),
                        closes_history=closes_history,
                        session_index=index,
                        fee_policy=fee_policy,
                    )
                )
            equity_curve.append(
                EquityPoint(trade_date, cash, market_value, cash + market_value, stale)
            )
        return BacktestResult(tuple(orders), tuple(fills), tuple(lots), tuple(equity_curve), cash)

    def _execute(
        self,
        intent,
        trade_date,
        bar,
        cash,
        lots,
        instrument,
        fee_policy,
        slippage_policy,
        max_volume_participation,
    ):
        if bar is None or bar.get("open") is None:
            return (
                SimulatedOrder(
                    f"order-{intent.client_order_id}",
                    intent.client_order_id,
                    intent.instrument_id,
                    intent.side,
                    intent.quantity,
                    0,
                    0,
                    None,
                    SimulatedOrderStatus.EXPIRED,
                    trade_date,
                    trade_date,
                    "BAR_MISSING",
                ),
                None,
            )
        requested = intent.quantity
        quantity = requested
        if intent.side == OrderSide.SELL:
            try:
                quantity = validate_sell_quantity(
                    tuple(lots), intent.instrument_id, quantity, trade_date
                )
            except BacktestRuleError as error:
                return (
                    SimulatedOrder(
                        f"order-{intent.client_order_id}",
                        intent.client_order_id,
                        intent.instrument_id,
                        intent.side,
                        intent.quantity,
                        0,
                        0,
                        None,
                        SimulatedOrderStatus.REJECTED,
                        trade_date,
                        trade_date,
                        error.code,
                    ),
                    None,
                )
        if max_volume_participation is not None:
            volume = bar.get("volume")
            if volume is None or Decimal(str(volume)) <= 0:
                return (
                    SimulatedOrder(
                        f"order-{intent.client_order_id}",
                        intent.client_order_id,
                        intent.instrument_id,
                        intent.side,
                        intent.quantity,
                        0,
                        0,
                        None,
                        SimulatedOrderStatus.REJECTED,
                        trade_date,
                        trade_date,
                        "VOLUME_UNAVAILABLE",
                    ),
                    None,
                )
            max_raw = int(Decimal(str(volume)) * max_volume_participation)
            volume_limited = round_lot(max_raw, instrument.lot_size)
            if volume_limited < instrument.lot_size:
                return (
                    SimulatedOrder(
                        f"order-{intent.client_order_id}",
                        intent.client_order_id,
                        intent.instrument_id,
                        intent.side,
                        intent.quantity,
                        0,
                        0,
                        None,
                        SimulatedOrderStatus.REJECTED,
                        trade_date,
                        trade_date,
                        "VOLUME_TOO_LOW",
                    ),
                    None,
                )
            quantity = min(quantity, volume_limited)
        raw = Decimal(str(bar["open"]))
        try:
            validate_execution_price(
                raw,
                limit_up=_decimal_or_none(bar.get("limit_up")),
                limit_down=_decimal_or_none(bar.get("limit_down")),
                side=intent.side.value,
            )
            fill_price, slippage = apply_slippage(
                raw, slippage_policy, side=intent.side.value, tick=instrument.price_tick
            )
            commission, stamp, transfer, total = calculate_fees(
                security_type=instrument.security_type,
                side=intent.side.value,
                quantity=quantity,
                price=fill_price,
                policy=fee_policy,
            )
            if intent.side == OrderSide.BUY and quantity * fill_price + total > cash:
                raise BacktestRuleError("INSUFFICIENT_CASH", "现金不足")
        except BacktestRuleError as error:
            return (
                SimulatedOrder(
                    f"order-{intent.client_order_id}",
                    intent.client_order_id,
                    intent.instrument_id,
                    intent.side,
                    intent.quantity,
                    0,
                    0,
                    None,
                    SimulatedOrderStatus.REJECTED,
                    trade_date,
                    trade_date,
                    error.code,
                ),
                None,
            )
        status = (
            SimulatedOrderStatus.PARTIALLY_FILLED
            if quantity < requested
            else SimulatedOrderStatus.FILLED
        )
        order = SimulatedOrder(
            f"order-{intent.client_order_id}",
            intent.client_order_id,
            intent.instrument_id,
            intent.side,
            requested,
            quantity,
            quantity,
            fill_price,
            status,
            trade_date,
            trade_date,
            None,
        )
        return order, SimulatedFill(
            f"fill-{intent.client_order_id}",
            order.order_id,
            intent.instrument_id,
            intent.side,
            quantity,
            raw,
            slippage,
            fill_price,
            commission,
            stamp,
            transfer,
            total,
            trade_date,
        )

    @staticmethod
    def _market_value(
        lots: list[PositionLot],
        bars_today: dict[str, dict[str, object]],
        last_valid_close: dict[str, Decimal],
    ) -> tuple[Decimal, bool]:
        total = Decimal("0")
        stale = False
        for lot in lots:
            bar = bars_today.get(lot.instrument_id)
            if bar is not None and bar.get("close") is not None:
                close = Decimal(str(bar["close"]))
            else:
                close = last_valid_close.get(lot.instrument_id, lot.cost_price)
                stale = True
            total += lot.remaining_quantity * close
        return total, stale


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))
