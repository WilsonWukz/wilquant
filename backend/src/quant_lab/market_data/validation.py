from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

from quant_lab.market_data.domain import (
    Bar,
    IssueSeverity,
    QualityIssue,
    QualityStatus,
    ValidatedBar,
    ValidationResult,
)


def _issue(row_number: int, bar: Bar, field: str, code: str, message: str) -> QualityIssue:
    return QualityIssue(row_number, bar.symbol, field, IssueSeverity.ERROR, code, message)


def validate_bars(indexed_bars: list[tuple[int, Bar]]) -> ValidationResult:
    if not indexed_bars:
        return ValidationResult(
            (),
            (
                QualityIssue(
                    None,
                    None,
                    None,
                    IssueSeverity.FATAL,
                    "EMPTY_FILE",
                    "文件不包含数据行",
                ),
            ),
        )
    issues: list[QualityIssue] = []
    rows: list[ValidatedBar] = []
    seen: set[tuple[str, str, object]] = set()
    previous_close: dict[str, Decimal] = {}
    previous_date: dict[str, date] = {}

    for row_number, original_bar in indexed_bars:
        bar_issues: list[QualityIssue] = []
        if min(original_bar.open, original_bar.high, original_bar.low, original_bar.close) <= 0:
            bar_issues.append(
                _issue(row_number, original_bar, "price", "NON_POSITIVE_PRICE", "价格必须大于零")
            )
        if original_bar.volume < 0:
            bar_issues.append(
                _issue(row_number, original_bar, "volume", "NEGATIVE_VOLUME", "成交量不得小于零")
            )
        if original_bar.amount < 0:
            bar_issues.append(
                _issue(row_number, original_bar, "amount", "NEGATIVE_AMOUNT", "成交额不得小于零")
            )
        if original_bar.high < original_bar.low:
            bar_issues.append(
                _issue(row_number, original_bar, "high", "HIGH_BELOW_LOW", "最高价不得低于最低价")
            )
        if not original_bar.low <= original_bar.open <= original_bar.high:
            bar_issues.append(
                _issue(
                    row_number,
                    original_bar,
                    "open",
                    "OPEN_OUT_OF_RANGE",
                    "开盘价必须位于最高价和最低价之间",
                )
            )
        if not original_bar.low <= original_bar.close <= original_bar.high:
            bar_issues.append(
                _issue(
                    row_number,
                    original_bar,
                    "close",
                    "CLOSE_OUT_OF_RANGE",
                    "收盘价必须位于最高价和最低价之间",
                )
            )

        key = (original_bar.instrument_id, original_bar.frequency.value, original_bar.trade_date)
        if key in seen:
            bar_issues.append(
                _issue(
                    row_number,
                    original_bar,
                    "trade_date",
                    "DUPLICATE_BAR",
                    "相同标的、频率和交易日重复",
                )
            )
        seen.add(key)

        prior_date = previous_date.get(original_bar.instrument_id)
        if prior_date is not None and original_bar.trade_date < prior_date:
            bar_issues.append(
                _issue(row_number, original_bar, "trade_date", "OUT_OF_ORDER", "交易日期顺序异常")
            )
        previous_date[original_bar.instrument_id] = original_bar.trade_date

        warning_issues: list[QualityIssue] = []
        if original_bar.volume == 0:
            warning_issues.append(
                QualityIssue(
                    row_number,
                    original_bar.symbol,
                    "volume",
                    IssueSeverity.WARNING,
                    "ZERO_VOLUME",
                    "成交量为零",
                )
            )
        if original_bar.amount == 0:
            warning_issues.append(
                QualityIssue(
                    row_number,
                    original_bar.symbol,
                    "amount",
                    IssueSeverity.WARNING,
                    "ZERO_AMOUNT",
                    "成交额为零",
                )
            )
        prior_close = previous_close.get(original_bar.instrument_id)
        if prior_close is not None and abs(original_bar.close / prior_close - 1) > Decimal("0.30"):
            warning_issues.append(
                QualityIssue(
                    row_number,
                    original_bar.symbol,
                    "close",
                    IssueSeverity.WARNING,
                    "EXTREME_PRICE_JUMP",
                    "相邻收盘价绝对涨幅超过30%",
                )
            )
        previous_close[original_bar.instrument_id] = original_bar.close

        issues.extend(bar_issues)
        issues.extend(warning_issues)
        if bar_issues:
            status = QualityStatus.REJECTED
        elif warning_issues:
            status = QualityStatus.WARNING
        else:
            status = QualityStatus.ACCEPTED
        rows.append(ValidatedBar(row_number, replace(original_bar, quality_status=status), status))

    return ValidationResult(tuple(rows), tuple(issues))
