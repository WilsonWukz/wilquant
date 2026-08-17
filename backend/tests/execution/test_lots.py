from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from quant_lab.execution.lots import (
    LotSnapshot,
    plan_sell_lot_consumption,
    realized_cost_basis,
)
from quant_lab.paper.errors import PaperError


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


def test_fifo_consumption_across_two_lots():
    a = _lot("a", date(2026, 1, 5), 100, Decimal("10"))
    b = _lot("b", date(2026, 1, 6), 100, Decimal("20"))
    result = plan_sell_lot_consumption((b, a), 150)
    assert result[0].lot_id == "a"
    assert result[0].consumed_quantity == 100
    assert result[1].lot_id == "b"
    assert result[1].consumed_quantity == 50


def test_partial_consumption_of_one_lot():
    lot = _lot("a", date(2026, 1, 5), 100, Decimal("10"))
    result = plan_sell_lot_consumption((lot,), 60)
    assert result[0].consumed_quantity == 60
    assert result[0].remaining_quantity == 40


def test_cannot_consume_more_than_sellable():
    lot = _lot("a", date(2026, 1, 5), 100, Decimal("10"))
    with pytest.raises(PaperError, match="INSUFFICIENT_SELLABLE"):
        plan_sell_lot_consumption((lot,), 150)


def test_realized_cost_basis():
    a = _lot("a", date(2026, 1, 5), 100, Decimal("10"))
    b = _lot("b", date(2026, 1, 6), 100, Decimal("20"))
    result = plan_sell_lot_consumption((a, b), 150)
    assert realized_cost_basis(result) == Decimal("2000")
