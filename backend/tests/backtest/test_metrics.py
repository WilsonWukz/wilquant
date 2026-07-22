from datetime import date
from decimal import Decimal

from quant_lab.backtest.domain import EquityPoint
from quant_lab.backtest.metrics import calculate_metrics


def test_metrics_known_small_equity_curve():
    curve = (
        EquityPoint(date(2026, 1, 2), Decimal("100"), Decimal("0"), Decimal("100"), False),
        EquityPoint(date(2026, 1, 5), Decimal("110"), Decimal("0"), Decimal("110"), False),
    )
    metrics = calculate_metrics(curve, (), ())
    assert metrics["initial_equity"] == Decimal("100")
    assert metrics["final_equity"] == Decimal("110")
    assert metrics["total_return"] == Decimal("0.1")
