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

    @property
    def instruments(self) -> tuple[InstrumentSpec, ...]:
        return (self.instrument,)

    def on_close(
        self,
        *,
        signal_date: date,
        execution_date: date | None,
        bars: dict[str, dict[str, object]],
        cash: Decimal,
        equity: Decimal,
        lots: tuple[PositionLot, ...],
        closes_history: dict[str, list[Decimal]],
        session_index: int,
        fee_policy: FeePolicy,
    ) -> tuple[OrderIntent, ...]:
        if execution_date is None or signal_date < self.first_trade_date:
            return ()
        bar = bars.get(self.instrument.instrument_id)
        if bar is None:
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

    def on_close(
        self,
        *,
        signal_date: date,
        execution_date: date | None,
        bars: dict[str, dict[str, object]],
        cash: Decimal,
        equity: Decimal,
        lots: tuple[PositionLot, ...],
        closes_history: dict[str, list[Decimal]],
        session_index: int,
        fee_policy: FeePolicy,
    ) -> tuple[OrderIntent, ...]:
        if execution_date is None:
            return ()
        if session_index < self.lookback_sessions:
            return ()
        if self.rebalance_every_n_sessions < 1:
            return ()
        if session_index % self.rebalance_every_n_sessions != 0:
            return ()
        selected = self.select(closes_history)
        selected_set = set(selected)
        intents: list[OrderIntent] = []
        for lot in lots:
            if (
                lot.instrument_id not in selected_set
                and lot.remaining_quantity > 0
                and lot.sellable_from_date <= signal_date
            ):
                intents.append(
                    OrderIntent(
                        client_order_id=(
                            f"rotation-sell-{execution_date.isoformat()}-{lot.instrument_id}"
                        ),
                        instrument_id=lot.instrument_id,
                        side=OrderSide.SELL,
                        quantity=lot.remaining_quantity,
                        order_type=OrderType.MARKET_ON_OPEN_SIMULATED,
                        signal_date=signal_date,
                        intended_execution_date=execution_date,
                        strategy_reason="ROTATION_SELL",
                        strategy_metadata={},
                    )
                )
        if selected:
            per_weight = self.target_gross_exposure / Decimal(len(selected))
            for instrument_id in selected:
                spec = self._instrument_spec(instrument_id)
                history = closes_history.get(instrument_id)
                if not history:
                    continue
                close = history[-1]
                if close <= 0:
                    continue
                current = sum(
                    lot.remaining_quantity
                    for lot in lots
                    if lot.instrument_id == instrument_id
                )
                target_quantity = (
                    int((equity * per_weight / close) // spec.lot_size) * spec.lot_size
                )
                if target_quantity > current:
                    intents.append(
                        OrderIntent(
                            client_order_id=(
                                f"rotation-buy-{execution_date.isoformat()}-{instrument_id}"
                            ),
                            instrument_id=instrument_id,
                            side=OrderSide.BUY,
                            quantity=target_quantity - current,
                            order_type=OrderType.MARKET_ON_OPEN_SIMULATED,
                            signal_date=signal_date,
                            intended_execution_date=execution_date,
                            strategy_reason="ROTATION_BUY",
                            strategy_metadata={"target_weight": str(per_weight)},
                        )
                    )
        return tuple(intents)

    def _instrument_spec(self, instrument_id: str) -> InstrumentSpec:
        for spec in self.instruments:
            if spec.instrument_id == instrument_id:
                return spec
        raise StrategySpecError(f"unknown instrument {instrument_id}")
