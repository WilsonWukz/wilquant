import hashlib
from pathlib import Path

import duckdb
import pytest

from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.providers import (
    DataSourceInput,
    LocalCsvMarketDataProvider,
    LocalParquetMarketDataProvider,
    SyntheticDataProvider,
)

CSV_BYTES = (
    b"symbol,exchange,trade_date,open,high,low,close,volume,amount\n"
    b"600000,XSHG,2026-07-17,10.1,10.8,10.0,10.5,1200,12500.25\n"
)


def source_input(path: Path) -> DataSourceInput:
    return DataSourceInput(path, path.name, hashlib.sha256(path.read_bytes()).hexdigest())


def test_csv_provider_reads_utf8_bom_and_returns_explicit_mapping(tmp_path: Path) -> None:
    path = tmp_path / "bars.csv"
    path.write_bytes(b"\xef\xbb\xbf" + CSV_BYTES)
    provider = LocalCsvMarketDataProvider()

    inspection = provider.inspect(source_input(path))
    batch = provider.load_bars(source_input(path))

    assert inspection.columns[0] == "symbol"
    assert inspection.suggested_mapping["trade_date"] == "trade_date"
    assert inspection.row_count == 1
    assert batch.rows[0].row_number == 2
    assert batch.rows[0].values["close"] == "10.5"


def test_csv_provider_reports_encoding_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(b"symbol\n\xff")

    with pytest.raises(ImportDataError) as error:
        LocalCsvMarketDataProvider().inspect(source_input(path))

    assert error.value.category == "ENCODING_ERROR"


def test_parquet_provider_reads_schema_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "bars.parquet"
    connection = duckdb.connect()
    try:
        connection.execute(
            "COPY (SELECT '600000' AS symbol, 'XSHG' AS exchange, "
            "DATE '2026-07-17' AS trade_date, 10.1 AS open, 10.8 AS high, "
            "10.0 AS low, 10.5 AS close, 1200 AS volume, 12500.25 AS amount) "
            "TO ? (FORMAT PARQUET)",
            [str(path)],
        )
    finally:
        connection.close()

    provider = LocalParquetMarketDataProvider()
    inspection = provider.inspect(source_input(path))
    batch = provider.load_bars(source_input(path))

    assert inspection.row_count == 1
    assert "trade_date" in inspection.columns
    assert batch.rows[0].values["symbol"] == "600000"
    assert batch.rows[0].values["trade_date"] == "2026-07-17"


def test_synthetic_provider_can_build_invalid_case() -> None:
    provider = SyntheticDataProvider(case="high_below_low")

    batch = provider.load_bars(DataSourceInput(Path("synthetic"), "synthetic", "synthetic"))

    assert batch.rows[0].values["high"] == "9"
    assert batch.rows[0].values["low"] == "10"


@pytest.mark.parametrize(
    ("case", "expected_rows", "field", "expected_value"),
    [
        ("normal", 1, "symbol", "600000"),
        ("duplicate_date", 2, "trade_date", "2026-07-17"),
        ("missing_ohlc", 1, "open", ""),
        ("close_out_of_range", 1, "close", "11"),
        ("negative_price", 1, "open", "-1"),
        ("negative_volume", 1, "volume", "-1"),
        ("illegal_symbol", 1, "symbol", "ABC001"),
        ("non_trading_day", 1, "trade_date", "2026-07-18"),
        ("duplicate_record", 2, "symbol", "600000"),
        ("extreme_jump", 2, "close", "10.5"),
        ("wrong_type", 1, "open", "not-a-number"),
        ("empty", 0, None, None),
    ],
)
def test_synthetic_provider_builds_required_cases(
    case: str,
    expected_rows: int,
    field: str | None,
    expected_value: str | None,
) -> None:
    batch = SyntheticDataProvider(case=case).load_bars(
        DataSourceInput(Path("synthetic"), "synthetic", "synthetic")
    )

    assert len(batch.rows) == expected_rows
    if field is not None:
        assert batch.rows[0].values[field] == expected_value


@pytest.mark.parametrize(
    ("content", "expected_columns", "expected_rows"),
    [
        (b"symbol,trade_date\n600000,2026-07-17\n", ("symbol", "trade_date"), 1),
        (CSV_BYTES.replace(b"10.1", b"not-a-number", 1), None, 1),
        (b"", (), 0),
        (CSV_BYTES + CSV_BYTES.splitlines()[1] + b"\n", None, 2),
    ],
)
def test_csv_provider_preserves_incomplete_invalid_empty_and_duplicate_rows(
    tmp_path: Path,
    content: bytes,
    expected_columns: tuple[str, ...] | None,
    expected_rows: int,
) -> None:
    path = tmp_path / "case.csv"
    path.write_bytes(content)
    provider = LocalCsvMarketDataProvider()

    inspection = provider.inspect(source_input(path))
    batch = provider.load_bars(source_input(path))

    assert inspection.row_count == expected_rows
    assert len(batch.rows) == expected_rows
    if expected_columns is not None:
        assert inspection.columns == expected_columns


@pytest.mark.parametrize(
    ("select_sql", "expected_rows", "expected_columns"),
    [
        ("SELECT '600000' AS symbol, DATE '2026-07-17' AS trade_date", 1, 2),
        (
            "SELECT '600000' AS symbol, 'bad' AS open, 'XSHG' AS exchange, "
            "DATE '2026-07-17' AS trade_date",
            1,
            4,
        ),
        ("SELECT '600000' AS symbol WHERE false", 0, 1),
    ],
)
def test_parquet_provider_preserves_schema_and_problematic_rows(
    tmp_path: Path,
    select_sql: str,
    expected_rows: int,
    expected_columns: int,
) -> None:
    path = tmp_path / "case.parquet"
    connection = duckdb.connect()
    try:
        connection.execute(f"COPY ({select_sql}) TO ? (FORMAT PARQUET)", [str(path)])
    finally:
        connection.close()

    provider = LocalParquetMarketDataProvider()
    inspection = provider.inspect(source_input(path))
    batch = provider.load_bars(source_input(path))

    assert len(inspection.columns) == expected_columns
    assert inspection.row_count == expected_rows
    assert len(batch.rows) == expected_rows
