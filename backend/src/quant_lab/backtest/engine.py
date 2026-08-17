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
    sellable_quantity,
)
from quant_lab.execution.kernel import ExecutionKernel, ExecutionRequest, ExecutionStatus


@dataclass(frozen=True, slots=True)
class BacktestResult:
    orders: tuple[SimulatedOrder, ...]
    fills: tuple[SimulatedFill, ...]
    positions: tuple[PositionLot, ...]
    equity_curve: tuple[EquityPoint, ...]
    final_cash: Decimal


_STATUS_MAP = {
    ExecutionStatus.FILLED.value: SimulatedOrderStatus.FILLED,
    ExecutionStatus.PARTIALLY_FILLED.value: SimulatedOrderStatus.PARTIALLY_FILLED,
    ExecutionStatus.REJECTED.value: SimulatedOrderStatus.REJECTED,
    ExecutionStatus.EXPIRED.value: SimulatedOrderStatus.EXPIRED,
}


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
        request = ExecutionRequest(
            instrument_id=intent.instrument_id,
            side=intent.side.value,
            requested_quantity=intent.quantity,
            order_type=intent.order_type.value,
            limit_price=None,
            execution_date=trade_date,
            cash=cash,
            sellable_quantity=sellable_quantity(tuple(lots), intent.instrument_id, trade_date),
            instrument=instrument,
            bar=bar,
            fee_policy=fee_policy,
            slippage_policy=slippage_policy,
            max_volume_participation=max_volume_participation,
        )
        result = ExecutionKernel().execute(request)
        status = _STATUS_MAP[result.status]
        order = SimulatedOrder(
            f"order-{intent.client_order_id}",
            intent.client_order_id,
            intent.instrument_id,
            intent.side,
            result.requested_quantity,
            result.accepted_quantity,
            result.filled_quantity,
            result.fill_price,
            status,
            trade_date,
            trade_date,
            result.reject_reason,
        )
        if result.status in (
            ExecutionStatus.FILLED.value,
            ExecutionStatus.PARTIALLY_FILLED.value,
        ):
            fill = SimulatedFill(
                f"fill-{intent.client_order_id}",
                order.order_id,
                intent.instrument_id,
                intent.side,
                result.filled_quantity,
                result.raw_price,
                result.slippage,
                result.fill_price,
                result.commission,
                result.stamp_tax,
                result.transfer_fee,
                result.total_fee,
                trade_date,
            )
            return order, fill
        return order, None

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
