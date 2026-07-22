from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import SimulatedOrderStatus
from quant_lab.backtest.engine import BacktestEngine
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.backtest.strategies import BuyAndHoldStrategy


def test_close_signal_executes_only_on_next_calendar_session_open():
    instrument = InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={
            date(2026, 1, 2): {"open": Decimal("10"), "close": Decimal("10")},
            date(2026, 1, 5): {"open": Decimal("11"), "close": Decimal("12")},
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
    instrument = InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))
    result = BacktestEngine().run(
        sessions=(date(2026, 1, 2), date(2026, 1, 5)),
        bars_by_date={date(2026, 1, 2): {"open": Decimal("10"), "close": Decimal("10")}},
        strategy=BuyAndHoldStrategy(instrument, Decimal("0.5"), date(2026, 1, 1)),
        initial_cash=Decimal("100000"),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
    )
    assert not result.fills
    assert result.orders[0].status == SimulatedOrderStatus.EXPIRED
