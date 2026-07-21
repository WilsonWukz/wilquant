from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum


class Exchange(StrEnum):
    XSHG = "XSHG"
    XSHE = "XSHE"


class BarFrequency(StrEnum):
    DAILY = "DAILY"
    MINUTE_1 = "MINUTE_1"
    MINUTE_5 = "MINUTE_5"


class AdjustmentType(StrEnum):
    NONE = "NONE"
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
    UNKNOWN = "UNKNOWN"


class QualityStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    WARNING = "WARNING"
    REJECTED = "REJECTED"


class ImportBatchStatus(StrEnum):
    PENDING = "PENDING"
    PARSING = "PARSING"
    VALIDATING = "VALIDATING"
    PREVIEW_READY = "PREVIEW_READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    PUBLISH_FAILED = "PUBLISH_FAILED"
    STALE = "STALE"


class IssueSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


@dataclass(frozen=True, slots=True)
class InstrumentId:
    symbol: str
    exchange: Exchange

    @property
    def value(self) -> str:
        return f"{self.symbol}.{self.exchange.value}"


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: str
    symbol: str
    exchange: Exchange
    name: str
    instrument_type: str
    board: str | None
    currency: str
    lot_size: int
    price_tick: Decimal
    listing_date: date | None
    delisting_date: date | None
    is_st: bool
    supports_t0: bool
    data_source: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    exchange: Exchange
    frequency: BarFrequency
    timestamp: datetime
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    adjustment_type: AdjustmentType
    data_source: str
    source_batch_id: str
    ingested_at: datetime
    quality_status: QualityStatus = QualityStatus.ACCEPTED

    @property
    def instrument_id(self) -> str:
        return f"{self.symbol}.{self.exchange.value}"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    row_number: int | None
    symbol: str | None
    field_name: str | None
    severity: IssueSeverity
    issue_code: str
    message: str
    raw_value: str | None = None
    normalized_value: object | None = None
    instrument_id: str | None = None
    created_at: datetime | None = None
    exception_text: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewRecord:
    """Complete deterministic Preview control-plane record persisted atomically."""

    source_file_size: int
    field_mapping_json: str
    provider_version: str
    schema_version: str
    normalization_version: str
    quality_rules_version: str
    preview_fingerprint_version: str
    row_count: int
    accepted_count: int
    rejected_count: int
    warning_count: int
    preview_fingerprint: str
    preview_completed_at: datetime
    issues: tuple[QualityIssue, ...]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Reject replay metadata that cannot safely gate a future publication."""
        counts = (
            self.source_file_size,
            self.row_count,
            self.accepted_count,
            self.rejected_count,
            self.warning_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError("Preview sizes and counts must be non-negative integers")
        if self.accepted_count + self.rejected_count != self.row_count:
            raise ValueError("Preview accepted and rejected counts must equal row count")
        if self.warning_count > self.accepted_count:
            raise ValueError("Preview warning count cannot exceed accepted count")
        versions = (
            self.provider_version,
            self.schema_version,
            self.normalization_version,
            self.quality_rules_version,
            self.preview_fingerprint_version,
        )
        if any(not isinstance(value, str) or not value.strip() for value in versions):
            raise ValueError("Preview Provider and rule versions must be non-empty")
        if (
            len(self.preview_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.preview_fingerprint)
        ):
            raise ValueError("Preview fingerprint must be lowercase SHA-256 hex")
        if (
            self.preview_completed_at.tzinfo is None
            or self.preview_completed_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("Preview completion time must be UTC-aware")

        import json

        from quant_lab.market_data.fingerprints import canonical_json_bytes

        try:
            field_mapping = json.loads(self.field_mapping_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Preview field mapping must be canonical JSON") from exc
        if (
            not isinstance(field_mapping, dict)
            or not field_mapping
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in field_mapping.items()
            )
        ):
            raise ValueError("Preview field mapping must be a non-empty string map")
        if canonical_json_bytes(field_mapping).decode("utf-8") != self.field_mapping_json:
            raise ValueError("Preview field mapping must use canonical JSON key ordering")


@dataclass(frozen=True, slots=True)
class ValidatedBar:
    row_number: int
    bar: Bar
    quality_status: QualityStatus


@dataclass(frozen=True, slots=True)
class ValidationResult:
    rows: tuple[ValidatedBar, ...]
    issues: tuple[QualityIssue, ...]

    @property
    def accepted_count(self) -> int:
        return sum(row.quality_status is not QualityStatus.REJECTED for row in self.rows)

    @property
    def rejected_count(self) -> int:
        return sum(row.quality_status is QualityStatus.REJECTED for row in self.rows)

    @property
    def warning_count(self) -> int:
        return sum(row.quality_status is QualityStatus.WARNING for row in self.rows)
