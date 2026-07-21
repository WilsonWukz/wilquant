from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from quant_lab.market_data import normalization
from quant_lab.market_data import processing as processing_module
from quant_lab.market_data.domain import ValidationResult
from quant_lab.market_data.fingerprints import fingerprint_issue
from quant_lab.market_data.processing import process_market_data
from quant_lab.market_data.providers import (
    DataSourceInput,
    LocalCsvMarketDataProvider,
    LocalParquetMarketDataProvider,
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
    issue = next(item for item in result.issues if item.issue_code == "HIGH_BELOW_LOW")
    assert issue.instrument_id == "600000.XSHG"
    assert issue.raw_value == "9"
    assert str(issue.normalized_value) == "9"
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


def test_processing_uses_the_concrete_provider_version() -> None:
    baseline_provider = SyntheticDataProvider()

    class NextSyntheticProvider(SyntheticDataProvider):
        version = "synthetic@2"

    assert baseline_provider.version == "synthetic@1"
    assert LocalCsvMarketDataProvider.version == "local-csv@1"
    assert LocalParquetMarketDataProvider.version == "local-parquet@1"
    assert process(provider=baseline_provider).preview_fingerprint != process(
        provider=NextSyntheticProvider()
    ).preview_fingerprint


def test_preview_envelope_covers_issue_fingerprint_version_without_issues(monkeypatch) -> None:
    baseline = process()

    monkeypatch.setattr(
        processing_module,
        "ISSUE_FINGERPRINT_VERSION",
        "quality-issue-sha256@3",
    )

    assert baseline.issues == ()
    assert baseline.preview_fingerprint != process().preview_fingerprint


def test_processing_canonically_sorts_equivalent_validator_issues(monkeypatch) -> None:
    baseline = process("high_below_low")
    validate = processing_module.validate_bars

    def validate_in_reverse(indexed_bars):
        result = validate(indexed_bars)
        return ValidationResult(result.rows, tuple(reversed(result.issues)))

    monkeypatch.setattr(processing_module, "validate_bars", validate_in_reverse)
    reordered = process("high_below_low")

    assert reordered.issues == baseline.issues
    assert reordered.rows[0].issue_fingerprints == baseline.rows[0].issue_fingerprints
    assert reordered.preview_fingerprint == baseline.preview_fingerprint


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


@pytest.mark.parametrize("field_name", ["open", "high", "low", "close"])
def test_non_positive_ohlc_issue_fingerprint_covers_the_specific_value(
    field_name: str,
) -> None:
    class NonPositiveProvider(SyntheticDataProvider):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            row = super().load_bars(source).rows[0]
            return RawBarBatch(
                (RawRow(row.row_number, {**row.values, field_name: self.value}),)
            )

    left = process(provider=NonPositiveProvider("-1"))
    right = process(provider=NonPositiveProvider("-2"))
    left_issue = next(
        item
        for item in left.issues
        if item.issue_code == "NON_POSITIVE_PRICE" and item.field_name == field_name
    )
    right_issue = next(
        item
        for item in right.issues
        if item.issue_code == "NON_POSITIVE_PRICE" and item.field_name == field_name
    )

    assert left_issue.raw_value == "-1"
    assert left_issue.normalized_value == Decimal("-1")
    assert fingerprint_issue(left_issue) != fingerprint_issue(right_issue)


def test_zero_volume_warning_carries_canonical_values() -> None:
    class ZeroVolumeProvider(SyntheticDataProvider):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            row = super().load_bars(source).rows[0]
            return RawBarBatch(
                (RawRow(row.row_number, {**row.values, "volume": self.value}),)
            )

    left = process(provider=ZeroVolumeProvider("0"))
    right = process(provider=ZeroVolumeProvider("00"))
    left_issue = next(item for item in left.issues if item.issue_code == "ZERO_VOLUME")
    right_issue = next(item for item in right.issues if item.issue_code == "ZERO_VOLUME")

    assert left_issue.raw_value == "0"
    assert left_issue.normalized_value == 0
    assert fingerprint_issue(left_issue) != fingerprint_issue(right_issue)


def test_zero_amount_warning_carries_canonical_values() -> None:
    class ZeroAmountProvider(SyntheticDataProvider):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            row = super().load_bars(source).rows[0]
            return RawBarBatch(
                (RawRow(row.row_number, {**row.values, "amount": self.value}),)
            )

    left = process(provider=ZeroAmountProvider("0"))
    right = process(provider=ZeroAmountProvider("0.00"))
    left_issue = next(item for item in left.issues if item.issue_code == "ZERO_AMOUNT")
    right_issue = next(item for item in right.issues if item.issue_code == "ZERO_AMOUNT")

    assert left_issue.raw_value == "0"
    assert left_issue.normalized_value == Decimal("0")
    assert fingerprint_issue(left_issue) != fingerprint_issue(right_issue)


def test_extreme_price_jump_warning_carries_canonical_values() -> None:
    class ExtremeCloseProvider(SyntheticDataProvider):
        def __init__(self, value: str) -> None:
            super().__init__("extreme_jump")
            self.value = value

        def load_bars(self, source: DataSourceInput) -> RawBarBatch:
            batch = super().load_bars(source)
            later = batch.rows[1]
            rows = (
                batch.rows[0],
                RawRow(
                    later.row_number,
                    {**later.values, "high": self.value, "close": self.value},
                ),
            )
            return RawBarBatch(rows)

    left = process(provider=ExtremeCloseProvider("21"))
    right = process(provider=ExtremeCloseProvider("22"))
    left_issue = next(
        item for item in left.issues if item.issue_code == "EXTREME_PRICE_JUMP"
    )
    right_issue = next(
        item for item in right.issues if item.issue_code == "EXTREME_PRICE_JUMP"
    )

    assert left_issue.raw_value == "21"
    assert left_issue.normalized_value == Decimal("21")
    assert fingerprint_issue(left_issue) != fingerprint_issue(right_issue)


def test_processing_does_not_persist_preview_bars() -> None:
    result = process()

    assert isinstance(result.rows, tuple)
    assert not hasattr(result, "save")
