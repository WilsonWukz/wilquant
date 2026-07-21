from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_lab.market_data import normalization
from quant_lab.market_data.processing import process_market_data
from quant_lab.market_data.providers import (
    DataSourceInput,
    RawBarBatch,
    RawRow,
    SyntheticDataProvider,
)

MAPPING = {
    field: field
    for field in (
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
}


def process(case: str = "normal", **changes: object):
    arguments: dict[str, object] = {
        "provider": SyntheticDataProvider(case),
        "source": DataSourceInput(Path("synthetic"), "bars.csv", "a" * 64),
        "source_size": 128,
        "field_mapping": MAPPING,
        "data_source": "synthetic",
        "source_batch_id": "batch-a",
    }
    arguments.update(changes)
    return process_market_data(**arguments)  # type: ignore[arg-type]


def test_processing_returns_immutable_rows_issues_statistics_and_fingerprint() -> None:
    result = process("high_below_low")

    assert result.row_count == 1
    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.warning_count == 0
    assert result.rows[0].bar is not None
    assert result.rows[0].quality_status.value == "REJECTED"
    assert result.issues[0].issue_code == "HIGH_BELOW_LOW"
    assert result.issues[0].instrument_id == "600000.XSHG"
    assert result.issues[0].raw_value == "9"
    assert str(result.issues[0].normalized_value) == "9"
    assert len(result.preview_fingerprint) == 64


def test_processing_is_stable_across_batch_identity(monkeypatch) -> None:
    first = datetime(2026, 7, 20, tzinfo=UTC)
    moments = iter((first, first + timedelta(microseconds=1)))

    class SequenceDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(moments)

    monkeypatch.setattr(normalization, "datetime", SequenceDateTime)
    left = process(source_batch_id="batch-a")
    right = process(source_batch_id="batch-b")

    assert left.rows[0].bar.source_batch_id != right.rows[0].bar.source_batch_id
    assert left.rows[0].bar.ingested_at != right.rows[0].bar.ingested_at
    assert left.preview_fingerprint == right.preview_fingerprint


def test_processing_changes_when_source_order_changes() -> None:
    forward = process("extreme_jump")

    class ReversedProvider(SyntheticDataProvider):
        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            batch = super().load_bars(source)
            return RawBarBatch(tuple(reversed(batch.rows)))

    reversed_result = process(provider=ReversedProvider("extreme_jump"))

    assert forward.preview_fingerprint != reversed_result.preview_fingerprint


def test_processing_covers_mapping_and_rule_versions() -> None:
    baseline = process()
    changed_mapping = dict(MAPPING)
    changed_mapping["close"] = "amount"
    mapped = process(field_mapping=changed_mapping)
    changed_version = process(quality_rules_version="quality@2")

    assert baseline.preview_fingerprint != mapped.preview_fingerprint
    assert baseline.preview_fingerprint != changed_version.preview_fingerprint
    assert baseline.accepted_count != mapped.accepted_count or baseline.rows != mapped.rows


def test_parse_rejection_is_included_without_empty_file_issue() -> None:
    result = process("wrong_type")

    assert result.rows[0].bar is None
    assert result.rows[0].quality_status.value == "REJECTED"
    assert result.rejected_count == 1
    assert {item.issue_code for item in result.issues} == {"TYPE_PARSE_ERROR"}


def test_parse_rejection_fingerprint_covers_canonical_raw_row() -> None:
    class InvalidOpenProvider(SyntheticDataProvider):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            row = super().load_bars(source).rows[0]
            return RawBarBatch((RawRow(row.row_number, {**row.values, "open": self.value}),))

    left = process(provider=InvalidOpenProvider("not-a-number"))
    right = process(provider=InvalidOpenProvider("still-not-a-number"))

    assert left.issues[0].raw_value != right.issues[0].raw_value
    assert left.preview_fingerprint != right.preview_fingerprint


def test_processing_does_not_persist_preview_bars() -> None:
    result = process()

    assert isinstance(result.rows, tuple)
    assert not hasattr(result, "save")
