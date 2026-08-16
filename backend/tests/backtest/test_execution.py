from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy, TopNMomentumRotationStrategy


def _instrument() -> InstrumentSpec:
    return InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))


def _run(fee_policy, slippage_policy=None, *, target_weight=Decimal("0.1")):
    return BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 5): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
        },
        strategy=BuyAndHoldStrategy(_instrument(), target_weight, date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=fee_policy,
        slippage_policy=slippage_policy or SlippagePolicy(),
    )


def test_commission_rate_changes_fill_fee_and_final_equity():
    low = _run(FeePolicy(stock_commission_rate=Decimal("0.0003")))
    high = _run(FeePolicy(stock_commission_rate=Decimal("0.003")))
    assert low.fills[0].total_fee != high.fills[0].total_fee
    assert low.final_cash != high.final_cash


def test_minimum_commission_is_enforced():
    low_min = _run(FeePolicy(stock_min_commission=Decimal("5")))
    high_min = _run(FeePolicy(stock_min_commission=Decimal("50")))
    assert high_min.fills[0].commission == Decimal("50")
    assert low_min.fills[0].commission == Decimal("5")
    assert low_min.fills[0].total_fee != high_min.fills[0].total_fee


def test_buy_slippage_moves_fill_price_against_the_buyer():
    zero = _run(FeePolicy(), SlippagePolicy(buy_bps=Decimal("0")))
    positive = _run(FeePolicy(), SlippagePolicy(buy_bps=Decimal("10")))
    assert positive.fills[0].fill_price > zero.fills[0].fill_price
    assert positive.fills[0].fill_price % Decimal("0.01") == 0


def _rotation_run(sell_bps: Decimal):
    instruments = (
        InstrumentSpec("A", "EQUITY", 100, Decimal("0.01")),
        InstrumentSpec("B", "EQUITY", 100, Decimal("0.01")),
    )
    strategy = TopNMomentumRotationStrategy(
        instruments=instruments,
        lookback_sessions=1,
        rebalance_every_n_sessions=1,
        top_n=1,
        target_gross_exposure=Decimal("0.1"),
        minimum_momentum=Decimal("0"),
        cash_reserve_ratio=Decimal("0"),
    )
    sessions = (
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
    )
    bars = {
        date(2026, 1, 2): {
            "A": {"open": Decimal("10"), "close": Decimal("10")},
            "B": {"open": Decimal("10"), "close": Decimal("10")},
        },
        date(2026, 1, 5): {
            "A": {"open": Decimal("10"), "close": Decimal("11")},
            "B": {"open": Decimal("10"), "close": Decimal("10")},
        },
        date(2026, 1, 6): {
            "A": {"open": Decimal("11"), "close": Decimal("12")},
            "B": {"open": Decimal("10"), "close": Decimal("10")},
        },
        date(2026, 1, 7): {
            "A": {"open": Decimal("12"), "close": Decimal("12")},
            "B": {"open": Decimal("10"), "close": Decimal("11")},
        },
        date(2026, 1, 8): {
            "A": {"open": Decimal("10"), "close": Decimal("10")},
            "B": {"open": Decimal("11"), "close": Decimal("11")},
        },
    }
    return BacktestEngine().run(
        sessions=sessions,
        bars_by_date=bars,
        strategy=strategy,
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(sell_bps=sell_bps),
    )


def test_sell_slippage_moves_fill_price_against_the_seller():
    zero = _rotation_run(Decimal("0"))
    positive = _rotation_run(Decimal("10"))
    zero_sell = [fill for fill in zero.fills if fill.side.value == "SELL"]
    positive_sell = [fill for fill in positive.fills if fill.side.value == "SELL"]
    assert zero_sell and positive_sell
    assert positive_sell[0].fill_price < zero_sell[0].fill_price
