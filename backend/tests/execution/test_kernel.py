from __future__ import annotations

from datetime import date
from decimal import Decimal

from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.execution.kernel import ExecutionKernel, ExecutionRequest, ExecutionStatus


def _instrument(security_type="EQUITY") -> InstrumentSpec:
    return InstrumentSpec("600000.XSHG", security_type, 100, Decimal("0.01"))


def _bar(**overrides) -> dict[str, object]:
    values: dict[str, object] = {
        "open": Decimal("10"),
        "high": Decimal("11"),
        "low": Decimal("9"),
        "close": Decimal("10"),
        "volume": Decimal("100000"),
    }
    values.update(overrides)
    return values


def _request(**overrides) -> ExecutionRequest:
    values = dict(
        instrument_id="600000.XSHG",
        side="BUY",
        requested_quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        execution_date=date(2026, 1, 5),
        cash=Decimal("100000"),
        sellable_quantity=0,
        instrument=_instrument(),
        bar=_bar(),
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
        max_volume_participation=None,
    )
    values.update(overrides)
    return ExecutionRequest(**values)


def _result(**overrides):
    return ExecutionKernel().execute(_request(**overrides))


def test_deterministic_identical_input():
    a = _result()
    b = _result()
    assert a == b


def test_bar_missing():
    result = _result(bar=None)
    assert result.status == ExecutionStatus.EXPIRED.value
    assert result.reject_reason == "BAR_MISSING"


def test_t1_sell_insufficient():
    result = _result(side="SELL", requested_quantity=100, sellable_quantity=0)
    assert result.status == ExecutionStatus.REJECTED.value
    assert result.reject_reason == "T1_SELL_RESTRICTED"


def test_valid_sell():
    result = _result(side="SELL", requested_quantity=100, sellable_quantity=100)
    assert result.status == ExecutionStatus.FILLED.value
    assert result.filled_quantity == 100


def test_price_limit_buy_block():
    result = _result(bar=_bar(limit_up=Decimal("10")))
    assert result.status == ExecutionStatus.REJECTED.value
    assert result.reject_reason == "LIMIT_UP_REJECTED"


def test_price_limit_sell_block():
    result = _result(side="SELL", sellable_quantity=100, bar=_bar(limit_down=Decimal("10")))
    assert result.status == ExecutionStatus.REJECTED.value
    assert result.reject_reason == "LIMIT_DOWN_REJECTED"


def test_slippage_buy_upward():
    result = _result(slippage_policy=SlippagePolicy(buy_bps=Decimal("10")))
    assert result.fill_price is not None
    assert result.fill_price > Decimal("10")


def test_slippage_sell_downward():
    result = _result(
        side="SELL", sellable_quantity=100, slippage_policy=SlippagePolicy(sell_bps=Decimal("10"))
    )
    assert result.fill_price is not None
    assert result.fill_price < Decimal("10")


def test_minimum_commission():
    result = _result(fee_policy=FeePolicy(stock_min_commission=Decimal("50")))
    assert result.commission == Decimal("50")


def test_etf_fee_semantics():
    result = _result(
        side="SELL",
        sellable_quantity=100,
        instrument=_instrument(security_type="ETF"),
    )
    assert result.stamp_tax == Decimal("0")


def test_volume_unavailable():
    result = _result(max_volume_participation=Decimal("0.5"), bar=_bar(volume=None))
    assert result.reject_reason == "VOLUME_UNAVAILABLE"


def test_volume_too_low():
    result = _result(
        max_volume_participation=Decimal("0.5"), bar=_bar(volume=Decimal("50"))
    )
    assert result.reject_reason == "VOLUME_TOO_LOW"


def test_volume_partial_fill():
    result = _result(
        requested_quantity=1000,
        max_volume_participation=Decimal("0.5"),
        bar=_bar(volume=Decimal("1500")),
    )
    assert result.status == ExecutionStatus.PARTIALLY_FILLED.value
    assert result.filled_quantity == 700
    assert result.remaining_quantity == 300


def test_insufficient_cash():
    result = _result(requested_quantity=100000, cash=Decimal("100"))
    assert result.status == ExecutionStatus.REJECTED.value
    assert result.reject_reason == "INSUFFICIENT_CASH"


def test_fully_filled_buy():
    result = _result(side="BUY", requested_quantity=100)
    assert result.status == ExecutionStatus.FILLED.value
    assert result.cash_delta == -(100 * Decimal("10") + result.total_fee)


def test_fully_filled_sell():
    result = _result(side="SELL", requested_quantity=100, sellable_quantity=100)
    assert result.status == ExecutionStatus.FILLED.value
    assert result.cash_delta > 0
