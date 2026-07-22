from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import OrderIntent, OrderSide, OrderType, PositionLot
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec


class StrategySpecError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BuyAndHoldStrategy:
    instrument: InstrumentSpec
    target_weight: Decimal
    first_trade_date: date

    def on_close(
        self,
        *,
        signal_date: date,
        execution_date: date | None,
        bar: dict[str, object] | None,
        cash: Decimal,
        equity: Decimal,
        lots: tuple[PositionLot, ...],
        fee_policy: FeePolicy,
    ) -> tuple[OrderIntent, ...]:
        if execution_date is None or signal_date < self.first_trade_date or bar is None:
            return ()
        current = sum(
            lot.remaining_quantity
            for lot in lots
            if lot.instrument_id == self.instrument.instrument_id
        )
        if current:
            return ()
        close = Decimal(str(bar["close"]))
        quantity = (
            int((equity * self.target_weight / close) // self.instrument.lot_size)
            * self.instrument.lot_size
        )
        if quantity <= 0 or quantity * close > cash:
            return ()
        return (
            OrderIntent(
                client_order_id=f"buy-and-hold-{execution_date.isoformat()}",
                instrument_id=self.instrument.instrument_id,
                side=OrderSide.BUY,
                quantity=quantity,
                order_type=OrderType.MARKET_ON_OPEN_SIMULATED,
                signal_date=signal_date,
                intended_execution_date=execution_date,
                strategy_reason="BUY_AND_HOLD",
                strategy_metadata={"target_weight": self.target_weight},
            ),
        )


@dataclass(frozen=True, slots=True)
class TopNMomentumRotationStrategy:
    instruments: tuple[InstrumentSpec, ...]
    lookback_sessions: int
    rebalance_every_n_sessions: int
    top_n: int
    target_gross_exposure: Decimal
    minimum_momentum: Decimal
    cash_reserve_ratio: Decimal

    def select(self, closes: dict[str, list[Decimal]]) -> tuple[str, ...]:
        if self.lookback_sessions < 1 or self.top_n < 1:
            raise StrategySpecError("momentum parameters must be positive")
        ranked = []
        for instrument_id, values in closes.items():
            if len(values) < self.lookback_sessions + 1:
                continue
            momentum = values[-1] / values[-1 - self.lookback_sessions] - Decimal("1")
            if momentum >= self.minimum_momentum:
                ranked.append((momentum, instrument_id))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[1] for item in ranked[: self.top_n])
