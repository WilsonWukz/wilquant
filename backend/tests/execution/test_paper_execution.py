from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quant_lab.backtest.rules import FeePolicy, InstrumentSpec, SlippagePolicy
from quant_lab.execution.lots import LotSnapshot
from quant_lab.paper.errors import PaperError
from quant_lab.paper.execution import (
    PaperExecutionEngine,
    PaperExecutionRequest,
    PaperOrderSnapshot,
)


def _order(**overrides) -> PaperOrderSnapshot:
    values = dict(
        order_id="o1",
        instrument_id="600000.XSHG",
        side="BUY",
        requested_quantity=100,
        order_type="MARKET_ON_OPEN_SIMULATED",
        limit_price=None,
        risk_decision="APPROVE",
    )
    values.update(overrides)
    return PaperOrderSnapshot(**values)


def _lot(lot_id, acquired, remaining, cost) -> LotSnapshot:
    return LotSnapshot(
        lot_id=lot_id,
        instrument_id="600000.XSHG",
        acquired_date=acquired,
        quantity=100,
        remaining_quantity=remaining,
        cost_price=cost,
        sellable_from_date=date(2026, 1, 5),
    )


def _request(**overrides) -> PaperExecutionRequest:
    values = dict(
        order=_order(),
        cash=Decimal("100000"),
        lots=(),
        instrument=InstrumentSpec("600000.XSHG", "EQUITY", 100, Decimal("0.01")),
        bar={"open": Decimal("10"), "close": Decimal("10")},
        fee_policy=FeePolicy(),
        slippage_policy=SlippagePolicy(),
        max_volume_participation=None,
        execution_date=date(2026, 1, 5),
        sellable_from_date=date(2026, 1, 6),
    )
    values.update(overrides)
    return PaperExecutionRequest(**values)


def test_approved_order_executes():
    result = PaperExecutionEngine().execute(_request())
    assert result.status == "FILLED"
    assert result.filled_quantity == 100


def test_non_approved_risk_decision_rejected():
    with pytest.raises(PaperError, match="RISK_DECISION_NOT_APPROVED"):
        PaperExecutionEngine().execute(_request(order=_order(risk_decision="REJECT")))


def test_buy_returns_new_lot():
    result = PaperExecutionEngine().execute(_request())
    assert result.new_lot is not None
    assert result.new_lot.quantity == 100
    assert result.new_lot.sellable_from_date == date(2026, 1, 6)


def test_sell_returns_lot_consumption_plan():
    lots = (_lot("a", date(2026, 1, 2), 100, Decimal("8")),)
    result = PaperExecutionEngine().execute(
        _request(
            order=_order(side="SELL"),
            lots=lots,
            bar={"open": Decimal("10"), "close": Decimal("10")},
        )
    )
    assert result.status == "FILLED"
    assert len(result.lot_consumptions) == 1
    assert result.lot_consumptions[0].consumed_quantity == 100


def test_realized_pnl_deterministic():
    lots = (_lot("a", date(2026, 1, 2), 100, Decimal("8")),)
    request = _request(
        order=_order(side="SELL"),
        lots=lots,
        bar={"open": Decimal("10"), "close": Decimal("10")},
    )
    a = PaperExecutionEngine().execute(request)
    b = PaperExecutionEngine().execute(request)
    assert a.realized_pnl_delta == b.realized_pnl_delta
    # 卖出 10*100=1000, 成本 8*100=800, fee=佣金+印花税+过户
    assert a.realized_pnl_delta is not None
    assert a.realized_pnl_delta < Decimal("200")


def test_partial_fill_includes_remaining_quantity():
    result = PaperExecutionEngine().execute(
        _request(
            order=_order(requested_quantity=1000),
            bar={"open": Decimal("10"), "close": Decimal("10"), "volume": Decimal("1500")},
            max_volume_participation=Decimal("0.5"),
        )
    )
    assert result.status == "PARTIALLY_FILLED"
    assert result.remaining_quantity == 300


def test_same_request_same_result():
    a = PaperExecutionEngine().execute(_request())
    b = PaperExecutionEngine().execute(_request())
    assert a == b
