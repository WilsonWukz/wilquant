from decimal import Decimal

from quant_lab.backtest.rules import InstrumentSpec
from quant_lab.backtest.strategies import TopNMomentumRotationStrategy


def test_momentum_ranking_is_deterministic_and_uses_only_available_history():
    strategy = TopNMomentumRotationStrategy(
        instruments=(
            InstrumentSpec("A", "EQUITY", 100, Decimal("0.01")),
            InstrumentSpec("B", "EQUITY", 100, Decimal("0.01")),
        ),
        lookback_sessions=2,
        rebalance_every_n_sessions=1,
        top_n=1,
        target_gross_exposure=Decimal("1"),
        minimum_momentum=Decimal("0"),
        cash_reserve_ratio=Decimal("0"),
    )
    assert strategy.select(
        {
            "A": [Decimal("1"), Decimal("1"), Decimal("2")],
            "B": [Decimal("1"), Decimal("1"), Decimal("1.5")],
        }
    ) == ("A",)
