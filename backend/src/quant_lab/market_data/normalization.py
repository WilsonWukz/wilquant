from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation

from quant_lab.market_data.domain import (
    AdjustmentType,
    Bar,
    BarFrequency,
    Exchange,
    InstrumentId,
)

SHANGHAI_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
_SYMBOL_PATTERN = re.compile(r"^\d{6}$")
_EXCHANGE_ALIASES = {
    "XSHG": Exchange.XSHG,
    "SSE": Exchange.XSHG,
    "SH": Exchange.XSHG,
    "XSHE": Exchange.XSHE,
    "SZSE": Exchange.XSHE,
    "SZ": Exchange.XSHE,
}


def normalize_instrument_id(symbol: str, exchange: str | None) -> InstrumentId:
    normalized_symbol = symbol.strip()
    if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
        raise ValueError("标的代码必须是六位数字")

    inferred: Exchange | None = None
    if normalized_symbol[0] in "569":
        inferred = Exchange.XSHG
    elif normalized_symbol[0] in "0123":
        inferred = Exchange.XSHE
    if inferred is None:
        raise ValueError("标的代码不属于当前支持的上海或深圳范围")

    if exchange is None or not exchange.strip():
        normalized_exchange = inferred
    else:
        matched_exchange = _EXCHANGE_ALIASES.get(exchange.strip().upper())
        if matched_exchange is None:
            raise ValueError("交易所无法识别")
        normalized_exchange = matched_exchange
        if normalized_exchange is not inferred:
            raise ValueError("交易所与标的代码冲突")
    return InstrumentId(normalized_symbol, normalized_exchange)


def _parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"{field_name}无法解析为十进制定点数") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name}必须是有限数值")
    return parsed


def normalize_daily_bar(
    *,
    symbol: str,
    exchange: str | None,
    trade_date: str,
    open_value: str,
    high_value: str,
    low_value: str,
    close_value: str,
    volume_value: str,
    amount_value: str,
    data_source: str,
    source_batch_id: str,
) -> Bar:
    instrument_id = normalize_instrument_id(symbol, exchange)
    try:
        parsed_date = date.fromisoformat(trade_date.strip())
    except ValueError as exc:
        raise ValueError("交易日期无法解析") from exc
    try:
        volume = int(volume_value.strip())
    except ValueError as exc:
        raise ValueError("成交量无法解析为整数") from exc
    return Bar(
        symbol=instrument_id.symbol,
        exchange=instrument_id.exchange,
        frequency=BarFrequency.DAILY,
        timestamp=datetime.combine(parsed_date, time(15), tzinfo=SHANGHAI_TZ),
        trade_date=parsed_date,
        open=_parse_decimal(open_value, "开盘价"),
        high=_parse_decimal(high_value, "最高价"),
        low=_parse_decimal(low_value, "最低价"),
        close=_parse_decimal(close_value, "收盘价"),
        volume=volume,
        amount=_parse_decimal(amount_value, "成交额"),
        adjustment_type=AdjustmentType.NONE,
        data_source=data_source,
        source_batch_id=source_batch_id,
        ingested_at=datetime.now(UTC),
    )
