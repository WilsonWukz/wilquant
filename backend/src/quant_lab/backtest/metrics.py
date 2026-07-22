from __future__ import annotations

from decimal import Decimal

from quant_lab.backtest.domain import EquityPoint, SimulatedFill, SimulatedOrder


def calculate_metrics(
    equity_curve: tuple[EquityPoint, ...],
    orders: tuple[SimulatedOrder, ...],
    fills: tuple[SimulatedFill, ...],
    *,
    annualized_days: int = 252,
    risk_free_rate: Decimal = Decimal("0"),
) -> dict[str, object]:
    if not equity_curve:
        return {"initial_equity": None, "final_equity": None, "total_return": None}
    values = [point.equity for point in equity_curve]
    initial = values[0]
    final = values[-1]
    returns = [
        values[index] / values[index - 1] - Decimal("1")
        for index in range(1, len(values))
        if values[index - 1] != 0
    ]
    mean = sum(returns, Decimal("0")) / len(returns) if returns else None
    variance = (
        sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
        if mean is not None and len(returns) > 1
        else None
    )
    volatility = variance.sqrt() * Decimal(annualized_days).sqrt() if variance is not None else None
    sharpe = (
        (
            (mean - risk_free_rate / Decimal(annualized_days))
            / (variance.sqrt())
            * Decimal(annualized_days).sqrt()
        )
        if variance and variance > 0 and mean is not None
        else None
    )
    peak = values[0]
    max_drawdown = Decimal("0")
    for value in values:
        peak = max(peak, value)
        if peak:
            max_drawdown = min(max_drawdown, value / peak - Decimal("1"))
    total_fees = sum((fill.total_fee for fill in fills), Decimal("0"))
    return {
        "initial_equity": initial,
        "final_equity": final,
        "total_return": final / initial - Decimal("1") if initial else None,
        "annualized_return": (final / initial)
        ** (Decimal(annualized_days) / Decimal(max(len(values) - 1, 1)))
        - Decimal("1")
        if initial and len(values) > 1
        else None,
        "annualized_volatility": volatility,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "trade_count": len(fills),
        "order_count": len(orders),
        "total_fees": total_fees,
        "total_commission": sum((fill.commission for fill in fills), Decimal("0")),
        "total_stamp_tax": sum((fill.stamp_tax for fill in fills), Decimal("0")),
        "total_transfer_fee": sum((fill.transfer_fee for fill in fills), Decimal("0")),
    }
