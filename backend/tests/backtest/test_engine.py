from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import SimulatedOrderStatus
from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy


def _instrument() -> InstrumentSpec:
    return InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))


def test_close_signal_executes_only_on_next_calendar_session_open():
    instrument = _instrument()
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 5): {"600000.XSHG": {"open": Decimal("11"), "close": Decimal("12")}},
        },
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.5"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
    )
    assert result.fills[0].trade_date == date(2026, 1, 5)
    assert result.fills[0].raw_price == Decimal("11")
    assert result.orders[0].status == SimulatedOrderStatus.FILLED


def test_missing_next_bar_expires_pending_order_without_fabricated_fill():
    instrument = _instrument()
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}}
        },
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.5"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
    )
    assert not result.fills
    assert result.orders[0].status == SimulatedOrderStatus.EXPIRED


def test_missing_bar_values_position_with_last_close_and_marks_stale():
    instrument = _instrument()
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 5): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 7): {"600000.XSHG": {"open": Decimal("12"), "close": Decimal("12")}},
        },
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.1"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
    )
    # 1/5 买入 1000 股; 1/6 无 bar 用 1/5 close 估值; 1/7 恢复 close.
    assert result.equity_curve[2].stale_valuation is True
    assert result.equity_curve[2].market_value == Decimal("10000")
    assert result.equity_curve[2].equity > Decimal("0")
    assert result.equity_curve[3].stale_valuation is False
    assert result.equity_curve[3].market_value == Decimal("12000")


def test_volume_participation_caps_fill_and_marks_partial():
    instrument = _instrument()
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 5): {
                "600000.XSHG": {
                    "open": Decimal("10"),
                    "close": Decimal("10"),
                    "volume": Decimal("1500"),
                }
            },
        },
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.1"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
        max_volume_participation=Decimal("0.5"),
    )
    order = result.orders[0]
    assert order.status == SimulatedOrderStatus.PARTIALLY_FILLED
    assert order.requested_quantity == 1000
    assert order.filled_quantity == 700


def test_volume_participation_rejects_missing_volume():
    instrument = _instrument()
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
            date(2026, 1, 5): {"600000.XSHG": {"open": Decimal("10"), "close": Decimal("10")}},
        },
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.1"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
        max_volume_participation=Decimal("0.5"),
    )
    order = result.orders[0]
    assert order.status == SimulatedOrderStatus.REJECTED
    assert order.reject_reason == "VOLUME_UNAVAILABLE"
