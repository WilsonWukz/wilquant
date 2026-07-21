from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quant_lab.market_data.domain import IssueSeverity, QualityIssue
from quant_lab.market_data.fingerprints import (
    canonical_json_bytes,
    fingerprint_issue,
    fingerprint_preview,
)
from quant_lab.market_data.versions import ISSUE_FINGERPRINT_VERSION


def issue(**changes: object) -> QualityIssue:
    values: dict[str, object] = {
        "row_number": 2,
        "symbol": "600000",
        "field_name": "high",
        "severity": IssueSeverity.ERROR,
        "issue_code": "HIGH_BELOW_LOW",
        "message": "最高价错误",
        "raw_value": "9.00",
        "normalized_value": Decimal("9.0"),
        "instrument_id": "600000.XSHG",
    }
    values.update(changes)
    return QualityIssue(**values)  # type: ignore[arg-type]


def preview_payload() -> dict[str, object]:
    return {
        "fingerprint_version": "preview-sha256@1",
        "source": {"sha256": "a" * 64, "size": 128},
        "provider": {"name": "local_csv", "version": "1"},
        "schema_version": "market-bar@1",
        "normalization_version": "a-share-daily-normalization@1",
        "quality_rules_version": "a-share-daily-quality@1",
        "field_mapping": {"symbol": "证券代码", "close": "收盘"},
        "rows": [
            {
                "row_number": 2,
                "result": "NORMALIZED",
                "instrument_id": "600000.XSHG",
                "symbol": "600000",
                "exchange": "XSHG",
                "frequency": "DAILY",
                "trade_date": "2026-07-17",
                "timestamp": "2026-07-17T07:00:00.000000Z",
                "open": "10.1",
                "high": "10.8",
                "low": "10",
                "close": "10.5",
                "volume": 1200,
                "amount": "12500.25",
                "adjustment_type": "NONE",
                "quality_status": "ACCEPTED",
                "issue_fingerprints": [],
            }
        ],
        "statistics": {"row_count": 1, "accepted": 1, "rejected": 0, "warning": 0},
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("row_number", 3),
        ("instrument_id", "000001.XSHE"),
        ("symbol", "000001"),
        ("severity", IssueSeverity.WARNING),
        ("issue_code", "OPEN_OUT_OF_RANGE"),
        ("field_name", "open"),
        ("raw_value", "9.01"),
        ("normalized_value", Decimal("9.01")),
    ],
)
def test_issue_fingerprint_covers_canonical_identity(field: str, value: object) -> None:
    assert fingerprint_issue(issue()) != fingerprint_issue(issue(**{field: value}))


def test_issue_fingerprint_excludes_display_and_runtime_metadata() -> None:
    baseline = fingerprint_issue(issue())

    assert baseline == fingerprint_issue(issue(message="High price error"))
    assert baseline == fingerprint_issue(
        issue(
            created_at=datetime(2026, 7, 20, tzinfo=UTC),
            exception_text="ValueError: local path F:\\secret",
        )
    )
    assert len(baseline) == 64
    assert ISSUE_FINGERPRINT_VERSION == "quality-issue-sha256@2"


def test_issue_fingerprint_distinguishes_null_empty_and_normalizes_unicode_decimal() -> None:
    assert fingerprint_issue(issue(raw_value=None)) != fingerprint_issue(issue(raw_value=""))
    assert fingerprint_issue(issue(raw_value="e\u0301")) == fingerprint_issue(issue(raw_value="é"))
    assert fingerprint_issue(issue(normalized_value=Decimal("9.000"))) == fingerprint_issue(
        issue(normalized_value=Decimal("9"))
    )


def test_canonical_json_uses_sorted_utf8_nfc_decimal_and_utc_microseconds() -> None:
    shanghai = timezone(timedelta(hours=8))
    value = {
        "z": Decimal("1000.0000"),
        "text": "e\u0301",
        "at": datetime(2026, 7, 20, 15, 0, 0, 123, tzinfo=shanghai),
    }

    assert canonical_json_bytes(value) == (
        b'{"at":"2026-07-20T07:00:00.000123Z","text":"\xc3\xa9","z":"1000"}'
    )


def test_canonical_strings_normalize_all_line_endings_to_lf() -> None:
    expected = canonical_json_bytes({"text": "first\nsecond\nthird"})

    assert canonical_json_bytes({"text": "first\r\nsecond\rthird"}) == expected
    assert fingerprint_issue(issue(raw_value="first\r\nsecond")) == fingerprint_issue(
        issue(raw_value="first\nsecond")
    )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), float("nan")])
def test_canonical_json_rejects_non_finite_numbers(value: object) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": value})


def test_canonical_json_rejects_unsupported_objects() -> None:
    with pytest.raises(TypeError, match="Unsupported"):
        canonical_json_bytes({"value": object()})


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("source", "size"), 129),
        (("provider", "version"), "2"),
        (("schema_version",), "market-bar@2"),
        (("normalization_version",), "normalization@2"),
        (("quality_rules_version",), "quality@2"),
        (("field_mapping", "close"), "收盘价"),
        (("rows", 0, "close"), "10.6"),
        (("rows", 0, "quality_status"), "WARNING"),
        (("statistics", "warning"), 1),
    ],
)
def test_preview_fingerprint_covers_replay_inputs_and_results(
    path: tuple[object, ...], replacement: object
) -> None:
    left = preview_payload()
    right = preview_payload()
    target: object = right
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = replacement  # type: ignore[index]

    assert fingerprint_preview(left) != fingerprint_preview(right)


def test_preview_fingerprint_excludes_request_batch_and_ingestion_metadata() -> None:
    left = preview_payload()
    right = preview_payload()
    left.update(batch_id="batch-a", request_id="request-a", ingested_at="yesterday")
    right.update(batch_id="batch-b", request_id="request-b", ingested_at="today")

    assert fingerprint_preview(left) == fingerprint_preview(right)


@pytest.mark.parametrize(
    "metadata_key",
    [
        "database_id",
        "database_auto_id",
        "temporary_path",
        "temporary_file_path",
        "batch_execution_time",
        "execution_timestamp",
        "log_timestamp",
        "processing_duration_ms",
        "row_processing_duration_ms",
    ],
)
def test_preview_fingerprint_excludes_formal_runtime_metadata(metadata_key: str) -> None:
    left = preview_payload()
    right = preview_payload()
    left["runtime"] = {metadata_key: "left"}
    right["runtime"] = {metadata_key: "right"}

    assert fingerprint_preview(left) == fingerprint_preview(right)


def test_preview_fingerprint_preserves_source_row_order() -> None:
    left = preview_payload()
    first = left["rows"][0]  # type: ignore[index]
    second = dict(first)
    second.update(row_number=3, instrument_id="000001.XSHE", symbol="000001")
    left["rows"] = [first, second]
    right = preview_payload()
    right["rows"] = [second, first]

    assert fingerprint_preview(left) != fingerprint_preview(right)
