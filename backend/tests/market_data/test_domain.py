from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from quant_lab.market_data.domain import Exchange, Instrument, QualityStatus
from quant_lab.market_data.normalization import normalize_daily_bar, normalize_instrument_id


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        ("600000", None, "600000.XSHG"),
        ("000001", None, "000001.XSHE"),
        ("510300", "SSE", "510300.XSHG"),
        ("159915", "SZSE", "159915.XSHE"),
    ],
)
def test_normalizes_supported_a_share_instrument_ids(
    symbol: str,
    exchange: str | None,
    expected: str,
) -> None:
    instrument_id = normalize_instrument_id(symbol, exchange)

    assert instrument_id.value == expected


@pytest.mark.parametrize("symbol", ["12345", "ABC001", "430001"])
def test_rejects_unsupported_or_invalid_symbols(symbol: str) -> None:
    with pytest.raises(ValueError, match="标的代码"):
        normalize_instrument_id(symbol, None)


def test_rejects_exchange_that_conflicts_with_symbol() -> None:
    with pytest.raises(ValueError, match="交易所"):
        normalize_instrument_id("600000", "SZSE")


def test_daily_bar_uses_decimal_and_shanghai_close_timestamp() -> None:
    bar = normalize_daily_bar(
        symbol="600000",
        exchange="XSHG",
        trade_date="2026-07-17",
        open_value="10.10",
        high_value="10.80",
        low_value="10.00",
        close_value="10.50",
        volume_value="1200",
        amount_value="12500.25",
        data_source="fixture",
        source_batch_id="batch-1",
    )

    assert bar.exchange is Exchange.XSHG
    assert bar.trade_date == date(2026, 7, 17)
    assert bar.timestamp.hour == 15
    assert bar.timestamp.tzname() == "Asia/Shanghai"
    assert bar.timestamp.utcoffset().total_seconds() == 8 * 60 * 60
    assert bar.close == Decimal("10.50")
    assert bar.amount == Decimal("12500.25")
    assert bar.quality_status is QualityStatus.ACCEPTED


def test_instrument_has_complete_reference_metadata() -> None:
    now = datetime.now(UTC)
    instrument = Instrument(
        instrument_id="510300.XSHG",
        symbol="510300",
        exchange=Exchange.XSHG,
        name="沪深300ETF",
        instrument_type="ETF",
        board="MAIN",
        currency="CNY",
        lot_size=100,
        price_tick=Decimal("0.001"),
        listing_date=date(2012, 5, 28),
        delisting_date=None,
        is_st=False,
        supports_t0=False,
        data_source="fixture",
        created_at=now,
        updated_at=now,
    )

    assert instrument.instrument_id == "510300.XSHG"
    assert instrument.price_tick == Decimal("0.001")
