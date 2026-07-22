from datetime import date
from decimal import Decimal

from quant_lab.backtest.planner import plan_target_weight
from quant_lab.backtest.rules import FeePolicy, InstrumentSpec


def test_target_planner_sells_before_buying_and_rounds_to_lot():
    instrument = InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01"))
    plan = plan_target_weight(
        trade_date=date(2026, 1, 2),
        execution_date=date(2026, 1, 5),
        cash=Decimal("100000"),
        holdings=(),
        equity=Decimal("100000"),
        instrument=instrument,
        target_weight=Decimal("0.5"),
        reference_price=Decimal("10.03"),
        fee_policy=FeePolicy(),
    )
    assert not plan.sells
    assert plan.buys[0].quantity % 100 == 0
