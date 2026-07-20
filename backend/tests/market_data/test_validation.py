from dataclasses import replace

import pytest

from quant_lab.market_data.domain import IssueSeverity, QualityStatus
from quant_lab.market_data.normalization import normalize_daily_bar
from quant_lab.market_data.validation import validate_bars


def make_bar(trade_date: str = "2026-07-17"):
    return normalize_daily_bar(
        symbol="600000",
        exchange="XSHG",
        trade_date=trade_date,
        open_value="10.10",
        high_value="10.80",
        low_value="10.00",
        close_value="10.50",
        volume_value="1200",
        amount_value="12500.25",
        data_source="synthetic",
        source_batch_id="batch-1",
    )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"open": make_bar().open * -1}, "NON_POSITIVE_PRICE"),
        ({"high": make_bar().low - 1}, "HIGH_BELOW_LOW"),
        ({"open": make_bar().high + 1}, "OPEN_OUT_OF_RANGE"),
        ({"close": make_bar().low - 1}, "CLOSE_OUT_OF_RANGE"),
        ({"volume": -1}, "NEGATIVE_VOLUME"),
        ({"amount": make_bar().amount * -1}, "NEGATIVE_AMOUNT"),
    ],
)
def test_rejects_invalid_bar_relationships(changes: dict[str, object], code: str) -> None:
    result = validate_bars([(2, replace(make_bar(), **changes))])

    assert result.rows[0].quality_status is QualityStatus.REJECTED
    assert code in {issue.issue_code for issue in result.issues}
    assert all(issue.severity is IssueSeverity.ERROR for issue in result.issues)


def test_detects_duplicate_daily_bar() -> None:
    bar = make_bar()
    result = validate_bars([(2, bar), (3, bar)])

    assert result.rejected_count == 1
    assert any(
        issue.issue_code == "DUPLICATE_BAR" and issue.row_number == 3
        for issue in result.issues
    )


def test_detects_out_of_order_daily_bars() -> None:
    result = validate_bars([(2, make_bar("2026-07-17")), (3, make_bar("2026-07-16"))])

    assert result.rejected_count == 1
    assert any(issue.issue_code == "OUT_OF_ORDER" for issue in result.issues)


def test_zero_volume_and_extreme_jump_are_warnings() -> None:
    first = replace(make_bar("2026-07-16"), volume=0)
    second = replace(make_bar("2026-07-17"), close=make_bar().close * 2, high=make_bar().close * 2)

    result = validate_bars([(2, first), (3, second)])

    assert result.accepted_count == 2
    assert result.warning_count == 2
    assert all(row.quality_status is QualityStatus.WARNING for row in result.rows)


def test_empty_batch_has_a_fatal_quality_issue() -> None:
    result = validate_bars([])

    assert result.rows == ()
    assert len(result.issues) == 1
    assert result.issues[0].severity is IssueSeverity.FATAL
    assert result.issues[0].issue_code == "EMPTY_FILE"
