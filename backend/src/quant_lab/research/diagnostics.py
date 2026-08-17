from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ResearchDiagnosticPolicy:
    version: str = "1"
    high_fee_drag_ratio: Decimal = Decimal("0.02")
    high_turnover_threshold: Decimal = Decimal("1.0")
    concentrated_position_weight: Decimal = Decimal("0.5")
    frequent_cash_rejection_count: int = 5
    frequent_t1_rejection_count: int = 5
    low_trade_count_threshold: int = 3
    partial_fill_ratio_threshold: Decimal = Decimal("0.3")


_CASH_REASONS = {"INSUFFICIENT_CASH"}
_T1_REASONS = {"T1_SELL_RESTRICTED"}
_LOT_REASONS = {"QUANTITY_BELOW_LOT", "QUANTITY_NOT_LOT_ALIGNED", "LOT_SIZE_INVALID"}
_VOLUME_REASONS = {"VOLUME_UNAVAILABLE", "VOLUME_TOO_LOW"}
_BUY_LIMIT_REASONS = {"LIMIT_UP_REJECTED"}
_SELL_LIMIT_REASONS = {"LIMIT_DOWN_REJECTED"}


def _dec(value: object) -> Decimal:
    return Decimal(str(value))


def _safe_div(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


class ResearchDiagnosticsService:
    def __init__(self, reader, policy: ResearchDiagnosticPolicy | None = None) -> None:
        self.reader = reader
        self.policy = policy or ResearchDiagnosticPolicy()

    def compute(self, run, artifacts) -> dict[str, object]:
        orders_artifact = next((a for a in artifacts if a.artifact_type == "ORDERS"), None)
        fills_artifact = next((a for a in artifacts if a.artifact_type == "FILLS"), None)
        equity_artifact = next((a for a in artifacts if a.artifact_type == "EQUITY_CURVE"), None)
        metrics_artifact = next((a for a in artifacts if a.artifact_type == "METRICS"), None)

        orders = self.reader.read_rows(orders_artifact) if orders_artifact else []
        fills = self.reader.read_rows(fills_artifact) if fills_artifact else []
        equity = self.reader.read_rows(equity_artifact) if equity_artifact else []
        metrics = self.reader.read_json(metrics_artifact) if metrics_artifact else {}

        execution = self._execution(orders)
        portfolio = self._portfolio(equity, fills)
        cost = self._cost(fills, metrics, _dec(run.initial_cash))
        data_quality = {
            "stale_valuation_days": sum(
                1 for point in equity if point.get("stale_valuation") is True
            ),
            "bar_missing_count": execution["bar_missing_count"],
        }
        diagnostics = self._diagnostics(execution, portfolio, cost, data_quality, metrics)
        return {
            "run_id": run.backtest_run_id,
            "policy_version": self.policy.version,
            "summary": self._summary(diagnostics),
            "diagnostics": diagnostics,
            "execution": execution,
            "portfolio": portfolio,
            "cost": cost,
            "data_quality": data_quality,
        }

    def _execution(self, orders: list[dict]) -> dict[str, object]:
        rejected = [o for o in orders if o.get("status") == "REJECTED"]
        expired = [o for o in orders if o.get("status") == "EXPIRED"]
        partial = [o for o in orders if o.get("status") == "PARTIALLY_FILLED"]
        reason_counts: dict[str, int] = {}
        for order in rejected:
            reason = order.get("reject_reason") or "UNKNOWN"
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        return {
            "order_count": len(orders),
            "fill_count": len([o for o in orders if o.get("status") == "FILLED"]) + len(partial),
            "rejected_order_count": len(rejected),
            "expired_order_count": len(expired),
            "partial_fill_count": len(partial),
            "rejection_reason_counts": reason_counts,
            "cash_rejection_count": sum(reason_counts.get(r, 0) for r in _CASH_REASONS),
            "t1_rejection_count": sum(reason_counts.get(r, 0) for r in _T1_REASONS),
            "lot_size_rejection_count": sum(reason_counts.get(r, 0) for r in _LOT_REASONS),
            "volume_participation_trigger_count": sum(
                reason_counts.get(r, 0) for r in _VOLUME_REASONS
            )
            + len(partial),
            "price_limit_buy_block_count": sum(reason_counts.get(r, 0) for r in _BUY_LIMIT_REASONS),
            "price_limit_sell_block_count": sum(
                reason_counts.get(r, 0) for r in _SELL_LIMIT_REASONS
            ),
            "bar_missing_count": len(expired),
        }

    def _portfolio(self, equity: list[dict], fills: list[dict]) -> dict[str, object]:
        if not equity:
            return {
                "max_single_instrument_weight": None,
                "average_position_count": None,
                "max_position_count": None,
                "max_cash_ratio": None,
                "min_cash_ratio": None,
                "max_daily_turnover": None,
                "longest_drawdown_duration": 0,
                "longest_no_trade_period": 0,
            }
        cash_ratios: list[Decimal] = [
            r
            for r in (_safe_div(_dec(p["cash"]), _dec(p["equity"])) for p in equity)
            if r is not None
        ]
        position_counts: list[int] = []
        for point in equity:
            count = 0
            for fill in fills:
                if fill.get("trade_date") == point.get("trade_date") and fill.get("side") == "BUY":
                    count += 1
            position_counts.append(count)
        longest_drawdown = self._longest_drawdown(equity)
        longest_no_trade = self._longest_no_trade(fills)
        max_turnover = self._max_daily_turnover(fills, equity)
        return {
            "max_single_instrument_weight": None,
            "average_position_count": (
                _dec(sum(position_counts)) / _dec(len(position_counts)) if position_counts else None
            ),
            "max_position_count": max(position_counts) if position_counts else 0,
            "max_cash_ratio": _dec_text(max(cash_ratios)) if cash_ratios else None,
            "min_cash_ratio": _dec_text(min(cash_ratios)) if cash_ratios else None,
            "max_daily_turnover": _dec_text(max_turnover) if max_turnover is not None else None,
            "longest_drawdown_duration": longest_drawdown,
            "longest_no_trade_period": longest_no_trade,
        }

    def _cost(self, fills: list[dict], metrics: dict, initial_cash: Decimal) -> dict[str, object]:
        total_fees = _dec(metrics.get("total_fees", 0))
        total_commission = sum(
            (_dec(f.get("commission", 0)) for f in fills), Decimal("0")
        )
        stamp_tax_total = sum(
            (_dec(f.get("stamp_tax", 0)) for f in fills), Decimal("0")
        )
        transfer_fee_total = sum(
            (_dec(f.get("transfer_fee", 0)) for f in fills), Decimal("0")
        )
        slippage_cost = sum(
            (
                _dec(f.get("slippage", 0)) * _dec(f.get("quantity", 0))
                for f in fills
            ),
            Decimal("0"),
        )
        min_commission_triggers = sum(1 for f in fills if _dec(f.get("commission", 0)) > 0)
        final_equity = metrics.get("final_equity")
        gross_profit = (
            _dec(final_equity) - initial_cash if final_equity is not None else Decimal("0")
        )
        return {
            "total_fees": _dec_text(total_fees),
            "fees_to_initial_cash": _dec_text(_safe_div(total_fees, initial_cash)),
            "fees_to_gross_profit": _dec_text(_safe_div(total_fees, gross_profit)),
            "average_fee_per_fill": _dec_text(_safe_div(total_fees, _dec(len(fills)))),
            "minimum_commission_trigger_count": min_commission_triggers,
            "estimated_slippage_cost": _dec_text(slippage_cost),
            "stamp_tax_total": _dec_text(stamp_tax_total),
            "transfer_fee_total": _dec_text(transfer_fee_total),
            "total_commission": _dec_text(total_commission),
        }

    def _diagnostics(self, execution, portfolio, cost, data_quality, metrics) -> list[dict]:
        items: list[dict] = []
        fees_to_cash = cost["fees_to_initial_cash"]
        if fees_to_cash is not None and _dec(fees_to_cash) > self.policy.high_fee_drag_ratio:
            items.append(
                self._item("HIGH_FEE_DRAG", "WARNING", "费用占初始资金比例过高", fees_to_cash)
            )
        turnover = portfolio.get("max_daily_turnover")
        if turnover is not None and _dec(turnover) > self.policy.high_turnover_threshold:
            items.append(self._item("HIGH_TURNOVER", "WARNING", "单日换手率过高", turnover))
        if execution["cash_rejection_count"] >= self.policy.frequent_cash_rejection_count:
            items.append(
                self._item(
                    "FREQUENT_CASH_REJECTION",
                    "WARNING",
                    "现金不足拒绝次数过多",
                    execution["cash_rejection_count"],
                )
            )
        if execution["t1_rejection_count"] >= self.policy.frequent_t1_rejection_count:
            items.append(
                self._item(
                    "FREQUENT_T1_REJECTION",
                    "WARNING",
                    "T+1 卖出限制触发次数过多",
                    execution["t1_rejection_count"],
                )
            )
        if data_quality["stale_valuation_days"] > 0:
            items.append(
                self._item(
                    "STALE_VALUATION_USED",
                    "INFO",
                    "使用了最近有效收盘价的滞后估值",
                    data_quality["stale_valuation_days"],
                )
            )
        if data_quality["bar_missing_count"] > 0:
            items.append(
                self._item(
                    "DATA_COVERAGE_WARNING",
                    "WARNING",
                    "存在缺失 Bar 的交易日",
                    data_quality["bar_missing_count"],
                )
            )
        trade_count = metrics.get("trade_count")
        if trade_count is not None and int(trade_count) < self.policy.low_trade_count_threshold:
            items.append(self._item("LOW_TRADE_COUNT", "INFO", "成交次数偏低", trade_count))
        total_orders = execution["order_count"]
        if total_orders and (
            _dec(execution["partial_fill_count"]) / _dec(total_orders)
            > self.policy.partial_fill_ratio_threshold
        ):
            items.append(
                self._item(
                    "PARTIAL_FILL_FREQUENT",
                    "WARNING",
                    "部分成交比例偏高",
                    execution["partial_fill_count"],
                )
            )
        return items

    @staticmethod
    def _item(code: str, severity: str, message: str, value: object) -> dict:
        return {"code": code, "severity": severity, "message": message, "value": value}

    @staticmethod
    def _summary(diagnostics: list[dict]) -> dict:
        return {
            "total": len(diagnostics),
            "warning_count": sum(1 for d in diagnostics if d["severity"] == "WARNING"),
            "info_count": sum(1 for d in diagnostics if d["severity"] == "INFO"),
        }

    @staticmethod
    def _longest_drawdown(equity: list[dict]) -> int:
        peak = Decimal("0")
        start = None
        longest = 0
        for index, point in enumerate(equity):
            value = _dec(point["equity"])
            if value > peak:
                peak = value
                start = index
            elif start is not None and index - start > longest:
                longest = index - start
        return longest

    @staticmethod
    def _longest_no_trade(fills: list[dict]) -> int:
        if not fills:
            return 0
        dates = sorted({f["trade_date"] for f in fills})
        longest = 0
        for index in range(1, len(dates)):
            gap = _days_between(dates[index - 1], dates[index]) - 1
            longest = max(longest, gap)
        return longest

    @staticmethod
    def _max_daily_turnover(fills: list[dict], equity: list[dict]):
        if not fills:
            return None
        by_date: dict[str, Decimal] = {}
        for fill in fills:
            amount = _dec(fill["quantity"]) * _dec(fill["fill_price"])
            by_date[fill["trade_date"]] = by_date.get(fill["trade_date"], Decimal("0")) + amount
        equity_by_date = {p["trade_date"]: _dec(p["equity"]) for p in equity}
        turnovers: list[Decimal] = [
            t
            for t in (
                _safe_div(amount, equity_by_date.get(day, Decimal("1")))
                for day, amount in by_date.items()
            )
            if t is not None
        ]
        return max(turnovers) if turnovers else None


def _days_between(a: str, b: str) -> int:
    from datetime import date

    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _dec_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text
