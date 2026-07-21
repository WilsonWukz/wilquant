"""The single in-memory Phase 2A parse, normalize and validate operation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from quant_lab.market_data.domain import (
    Bar,
    IssueSeverity,
    QualityIssue,
    QualityStatus,
)
from quant_lab.market_data.fingerprints import (
    canonical_json_bytes,
    fingerprint_issue,
    fingerprint_preview,
)
from quant_lab.market_data.normalization import normalize_daily_bar, normalize_instrument_id
from quant_lab.market_data.providers import DataSourceInput, MarketDataProvider
from quant_lab.market_data.validation import validate_bars
from quant_lab.market_data.versions import (
    NORMALIZATION_RULES_VERSION,
    PREVIEW_FINGERPRINT_VERSION,
    PROVIDER_VERSION,
    QUALITY_RULES_VERSION,
    SCHEMA_VERSION,
)

REQUIRED_FIELDS = frozenset(
    {"symbol", "exchange", "trade_date", "open", "high", "low", "close", "volume", "amount"}
)


@dataclass(frozen=True, slots=True)
class ProcessedRow:
    row_number: int
    bar: Bar | None
    quality_status: QualityStatus
    issue_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProcessedMarketData:
    rows: tuple[ProcessedRow, ...]
    issues: tuple[QualityIssue, ...]
    row_count: int
    accepted_count: int
    rejected_count: int
    warning_count: int
    preview_fingerprint: str


def _bar_payload(bar: Bar) -> dict[str, object]:
    return {
        "instrument_id": bar.instrument_id,
        "symbol": bar.symbol,
        "exchange": bar.exchange,
        "frequency": bar.frequency,
        "trade_date": bar.trade_date,
        "timestamp": bar.timestamp,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
        "adjustment_type": bar.adjustment_type,
    }


def process_market_data(
    *,
    provider: MarketDataProvider,
    source: DataSourceInput,
    source_size: int,
    field_mapping: dict[str, str],
    data_source: str,
    source_batch_id: str,
    provider_version: str = PROVIDER_VERSION,
    schema_version: str = SCHEMA_VERSION,
    normalization_version: str = NORMALIZATION_RULES_VERSION,
    quality_rules_version: str = QUALITY_RULES_VERSION,
) -> ProcessedMarketData:
    missing = REQUIRED_FIELDS - field_mapping.keys()
    if missing:
        raise ValueError("Missing required field mapping")

    raw_batch = provider.load_bars(source)
    parsed: list[tuple[int, Bar]] = []
    parse_issues: list[QualityIssue] = []
    for raw_row in raw_batch.rows:
        try:
            values = {field: raw_row.values[field_mapping[field]] for field in REQUIRED_FIELDS}
            parsed.append(
                (
                    raw_row.row_number,
                    normalize_daily_bar(
                        symbol=values["symbol"],
                        exchange=values["exchange"],
                        trade_date=values["trade_date"],
                        open_value=values["open"],
                        high_value=values["high"],
                        low_value=values["low"],
                        close_value=values["close"],
                        volume_value=values["volume"],
                        amount_value=values["amount"],
                        data_source=data_source,
                        source_batch_id=source_batch_id,
                    ),
                )
            )
        except (KeyError, ValueError) as exc:
            raw_symbol = raw_row.values.get(field_mapping.get("symbol", ""))
            try:
                instrument_id = normalize_instrument_id(
                    raw_symbol or "",
                    raw_row.values.get(field_mapping.get("exchange", "")),
                ).value
            except ValueError:
                instrument_id = None
            issue = QualityIssue(
                row_number=raw_row.row_number,
                symbol=raw_symbol,
                field_name=None,
                severity=IssueSeverity.ERROR,
                issue_code="TYPE_PARSE_ERROR",
                message=str(exc),
                raw_value=canonical_json_bytes(raw_row.values).decode("utf-8"),
                instrument_id=instrument_id,
                normalized_value=None,
            )
            parse_issues.append(issue)

    validation = validate_bars(parsed) if parsed or not raw_batch.rows else None
    validation_rows = () if validation is None else validation.rows
    raw_by_row = {row.row_number: row for row in raw_batch.rows}
    bar_by_row = {row.row_number: row.bar for row in validation_rows}
    validation_issues = tuple(
        replace(
            issue,
            raw_value=(
                raw_by_row[issue.row_number].values.get(field_mapping.get(issue.field_name, ""))
                if issue.row_number is not None and issue.field_name is not None
                else None
            ),
            normalized_value=(
                getattr(bar_by_row[issue.row_number], issue.field_name, None)
                if issue.row_number is not None and issue.field_name is not None
                else None
            ),
            instrument_id=(
                bar_by_row[issue.row_number].instrument_id
                if issue.row_number is not None
                else None
            ),
        )
        for issue in (() if validation is None else validation.issues)
    )
    issues = tuple(parse_issues) + tuple(validation_issues)
    issues_by_row: dict[int, list[QualityIssue]] = {}
    for issue in issues:
        if issue.row_number is not None:
            issues_by_row.setdefault(issue.row_number, []).append(issue)
    validated_by_row = {row.row_number: row for row in validation_rows}

    processed_rows: list[ProcessedRow] = []
    fingerprint_rows: list[dict[str, object]] = []
    for raw_row in raw_batch.rows:
        validated = validated_by_row.get(raw_row.row_number)
        row_issues = tuple(issues_by_row.get(raw_row.row_number, ()))
        issue_hashes = tuple(fingerprint_issue(item) for item in row_issues)
        if validated is None:
            processed = ProcessedRow(raw_row.row_number, None, QualityStatus.REJECTED, issue_hashes)
            bar_payload: dict[str, object] | None = None
        else:
            processed = ProcessedRow(
                raw_row.row_number, validated.bar, validated.quality_status, issue_hashes
            )
            bar_payload = _bar_payload(validated.bar)
        processed_rows.append(processed)
        fingerprint_rows.append(
            {
                "row_number": raw_row.row_number,
                "result": "NORMALIZED" if processed.bar is not None else "PARSE_REJECTED",
                "bar": bar_payload,
                "quality_status": processed.quality_status,
                "issue_fingerprints": issue_hashes,
            }
        )

    accepted_count = sum(row.quality_status is not QualityStatus.REJECTED for row in processed_rows)
    rejected_count = sum(row.quality_status is QualityStatus.REJECTED for row in processed_rows)
    warning_count = sum(row.quality_status is QualityStatus.WARNING for row in processed_rows)
    statistics = {
        "row_count": len(raw_batch.rows),
        "accepted": accepted_count,
        "rejected": rejected_count,
        "warning": warning_count,
    }
    payload: dict[str, object] = {
        "fingerprint_version": PREVIEW_FINGERPRINT_VERSION,
        "source": {"sha256": source.sha256, "size": source_size},
        "provider": {"name": provider.name, "version": provider_version},
        "schema_version": schema_version,
        "normalization_version": normalization_version,
        "quality_rules_version": quality_rules_version,
        "field_mapping": field_mapping,
        "rows": fingerprint_rows,
        "issues": tuple(fingerprint_issue(item) for item in issues),
        "statistics": statistics,
    }
    return ProcessedMarketData(
        rows=tuple(processed_rows),
        issues=issues,
        row_count=len(raw_batch.rows),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        warning_count=warning_count,
        preview_fingerprint=fingerprint_preview(payload),
    )
