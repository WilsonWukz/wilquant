from datetime import date
from decimal import Decimal

import pytest

from quant_lab.backtest.domain import PositionLot
from quant_lab.backtest.rules import (
    BacktestRuleError,
    FeePolicy,
    SlippagePolicy,
    apply_slippage,
    calculate_fees,
    validate_sell_quantity,
)


def test_t1_rejects_same_day_purchase():
    lots = (
        PositionLot("600000.XSHG", date(2026, 1, 2), 100, 100, Decimal("10"), date(2026, 1, 5)),
    )
    with pytest.raises(BacktestRuleError, match=r"T\+1"):
        validate_sell_quantity(lots, "600000.XSHG", 100, date(2026, 1, 2))


def test_buy_slippage_moves_up_and_sell_moves_down_by_tick():
    policy = SlippagePolicy(buy_bps=Decimal("10"), sell_bps=Decimal("10"))
    buy, _ = apply_slippage(Decimal("10.00"), policy, side="BUY", tick=Decimal("0.01"))
    sell, _ = apply_slippage(Decimal("10.00"), policy, side="SELL", tick=Decimal("0.01"))
    assert buy > Decimal("10")
    assert sell < Decimal("10")


def test_stock_sell_fee_includes_stamp_tax_and_etf_does_not():
    policy = FeePolicy()
    stock = calculate_fees(
        security_type="EQUITY", side="SELL", quantity=100, price=Decimal("10"), policy=policy
    )
    etf = calculate_fees(
        security_type="ETF", side="SELL", quantity=100, price=Decimal("10"), policy=policy
    )
    assert stock[1] > etf[1]
