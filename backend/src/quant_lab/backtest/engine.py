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
    validate_execution_price,
    validate_sell_quantity,
)
from quant_lab.backtest.strategies import BuyAndHoldStrategy


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
        bars_by_date: dict[date, dict[str, object]],
        strategy: BuyAndHoldStrategy,
        initial_cash: Decimal,
        fee_policy: FeePolicy,
        slippage_policy: SlippagePolicy,
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
        for index, trade_date in enumerate(ordered_sessions):
            bar = bars_by_date.get(trade_date)
            next_date = ordered_sessions[index + 1] if index + 1 < len(ordered_sessions) else None
            for intent in tuple(pending):
                pending.remove(intent)
                order, fill = self._execute(
                    intent,
                    trade_date,
                    bar,
                    cash,
                    lots,
                    strategy.instrument,
                    fee_policy,
                    slippage_policy,
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
            if bar is not None:
                pending.extend(
                    strategy.on_close(
                        signal_date=trade_date,
                        execution_date=next_date,
                        bar=bar,
                        cash=cash,
                        equity=cash + self._market_value(lots, bar),
                        lots=tuple(lots),
                        fee_policy=fee_policy,
                    )
                )
            equity_curve.append(
                EquityPoint(
                    trade_date,
                    cash,
                    self._market_value(lots, bar),
                    cash + self._market_value(lots, bar),
                    False,
                )
            )
        return BacktestResult(tuple(orders), tuple(fills), tuple(lots), tuple(equity_curve), cash)

    def _execute(
        self, intent, trade_date, bar, cash, lots, instrument, fee_policy, slippage_policy
    ):
        if bar is None or bar.get("open") is None:
            order = SimulatedOrder(
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
            )
            return order, None
        quantity = intent.quantity
        if intent.side == OrderSide.SELL:
            try:
                quantity = validate_sell_quantity(
                    tuple(lots), intent.instrument_id, quantity, trade_date
                )
            except BacktestRuleError as error:
                return SimulatedOrder(
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
                ), None
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
            return SimulatedOrder(
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
            ), None
        order = SimulatedOrder(
            f"order-{intent.client_order_id}",
            intent.client_order_id,
            intent.instrument_id,
            intent.side,
            intent.quantity,
            quantity,
            quantity,
            fill_price,
            SimulatedOrderStatus.FILLED,
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
    def _market_value(lots, bar):
        if bar is None:
            return Decimal("0")
        close = Decimal(str(bar["close"]))
        return sum(lot.remaining_quantity * close for lot in lots)


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))
