from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

import duckdb

from quant_lab.market_data.errors import ImportDataError

STANDARD_FIELDS = (
    "symbol",
    "exchange",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
)
_ALIASES = {
    "symbol": ("symbol", "code", "证券代码"),
    "exchange": ("exchange", "market", "交易所"),
    "trade_date": ("trade_date", "date", "交易日期"),
    "open": ("open", "开盘"),
    "high": ("high", "最高"),
    "low": ("low", "最低"),
    "close": ("close", "收盘"),
    "volume": ("volume", "vol", "成交量"),
    "amount": ("amount", "turnover", "成交额"),
}


@dataclass(frozen=True, slots=True)
class DataSourceInput:
    path: Path
    original_filename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceInspection:
    provider_name: str
    columns: tuple[str, ...]
    suggested_mapping: dict[str, str]
    row_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RawRow:
    row_number: int
    values: dict[str, str]


@dataclass(frozen=True, slots=True)
class RawBarBatch:
    rows: tuple[RawRow, ...]


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    healthy: bool
    message: str


class MarketDataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def inspect(self, source: DataSourceInput) -> SourceInspection: ...

    def load_bars(self, source: DataSourceInput) -> RawBarBatch: ...

    def health_check(self) -> ProviderHealth: ...


def _suggest_mapping(columns: tuple[str, ...]) -> dict[str, str]:
    lowered = {column.casefold(): column for column in columns}
    suggestions: dict[str, str] = {}
    for standard_field, aliases in _ALIASES.items():
        for alias in aliases:
            matched = lowered.get(alias.casefold())
            if matched is not None:
                suggestions[standard_field] = matched
                break
    return suggestions


class LocalCsvMarketDataProvider:
    name = "local_csv"

    def _read(self, source: DataSourceInput) -> tuple[tuple[str, ...], tuple[RawRow, ...]]:
        try:
            with source.path.open("r", encoding="utf-8-sig", newline="") as input_file:
                reader = csv.DictReader(input_file)
                if reader.fieldnames is None:
                    return (), ()
                columns = tuple(reader.fieldnames)
                rows = tuple(
                    RawRow(
                        index,
                        {key: value or "" for key, value in row.items() if key is not None},
                    )
                    for index, row in enumerate(reader, start=2)
                )
                return columns, rows
        except UnicodeDecodeError as exc:
            raise ImportDataError("ENCODING_ERROR", "CSV 文件必须使用 UTF-8 编码") from exc
        except csv.Error as exc:
            raise ImportDataError("SCHEMA_ERROR", "CSV 结构无法解析") from exc

    def inspect(self, source: DataSourceInput) -> SourceInspection:
        columns, rows = self._read(source)
        return SourceInspection(
            self.name, columns, _suggest_mapping(columns), len(rows), source.sha256
        )

    def load_bars(self, source: DataSourceInput) -> RawBarBatch:
        _, rows = self._read(source)
        return RawBarBatch(rows)

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, "available")


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


class LocalParquetMarketDataProvider:
    name = "local_parquet"

    def _read(self, source: DataSourceInput) -> tuple[tuple[str, ...], tuple[RawRow, ...]]:
        connection = duckdb.connect()
        try:
            cursor = connection.execute("SELECT * FROM read_parquet(?)", [str(source.path)])
            columns = tuple(item[0] for item in cursor.description)
            rows = tuple(
                RawRow(index, dict(zip(columns, map(_stringify, values), strict=True)))
                for index, values in enumerate(cursor.fetchall(), start=1)
            )
            return columns, rows
        except duckdb.Error as exc:
            raise ImportDataError("SCHEMA_ERROR", "Parquet 文件无法解析") from exc
        finally:
            connection.close()

    def inspect(self, source: DataSourceInput) -> SourceInspection:
        columns, rows = self._read(source)
        return SourceInspection(
            self.name, columns, _suggest_mapping(columns), len(rows), source.sha256
        )

    def load_bars(self, source: DataSourceInput) -> RawBarBatch:
        _, rows = self._read(source)
        return RawBarBatch(rows)

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, "available")


class SyntheticDataProvider:
    name = "synthetic"

    def __init__(self, case: str = "normal") -> None:
        self._case = case

    def inspect(self, source: DataSourceInput) -> SourceInspection:
        batch = self.load_bars(source)
        return SourceInspection(
            self.name,
            STANDARD_FIELDS,
            _suggest_mapping(STANDARD_FIELDS),
            len(batch.rows),
            source.sha256,
        )

    def load_bars(self, source: DataSourceInput) -> RawBarBatch:
        values = {
            "symbol": "600000",
            "exchange": "XSHG",
            "trade_date": "2026-07-17",
            "open": "10.1",
            "high": "10.8",
            "low": "10.0",
            "close": "10.5",
            "volume": "1200",
            "amount": "12500.25",
        }
        if self._case == "normal":
            pass
        elif self._case == "high_below_low":
            values.update(high="9", low="10")
        elif self._case == "missing_ohlc":
            values["open"] = ""
        elif self._case == "close_out_of_range":
            values["close"] = "11"
        elif self._case == "negative_price":
            values["open"] = "-1"
        elif self._case == "negative_volume":
            values["volume"] = "-1"
        elif self._case == "illegal_symbol":
            values["symbol"] = "ABC001"
        elif self._case == "non_trading_day":
            values["trade_date"] = "2026-07-18"
        elif self._case == "wrong_type":
            values["open"] = "not-a-number"
        elif self._case == "empty":
            return RawBarBatch(())
        elif self._case in {"duplicate_date", "duplicate_record"}:
            return RawBarBatch((RawRow(1, values.copy()), RawRow(2, values.copy())))
        elif self._case == "extreme_jump":
            later = values.copy()
            later.update(trade_date="2026-07-18", high="22", close="21")
            return RawBarBatch((RawRow(1, values.copy()), RawRow(2, later)))
        else:
            raise ValueError(f"未知合成数据场景: {self._case}")
        return RawBarBatch((RawRow(1, values.copy()),))

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(True, "available")
