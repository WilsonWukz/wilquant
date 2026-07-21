"""Deterministic canonical serialization and market-data fingerprints."""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from quant_lab.market_data.domain import QualityIssue
from quant_lab.market_data.versions import ISSUE_FINGERPRINT_VERSION

_PREVIEW_EXCLUDED_KEYS = frozenset(
    {
        "batch_id",
        "request_id",
        "ingested_at",
        "database_id",
        "database_auto_id",
        "temporary_path",
        "temporary_file_path",
        "batch_execution_time",
        "execution_timestamp",
        "log_timestamp",
        "processing_duration_ms",
        "row_processing_duration_ms",
    }
)


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Canonical numbers must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _canonicalize(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        normalized_lines = value.replace("\r\n", "\n").replace("\r", "\n")
        return unicodedata.normalize("NFC", normalized_lines)
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Canonical numbers must be finite")
        raise TypeError("Unsupported canonical type: float")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Canonical timestamps must be timezone-aware")
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonicalize(value.value)
    if isinstance(value, dict):
        canonical: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Unsupported canonical mapping key")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in canonical:
                raise ValueError("Canonical mapping key collision after NFC normalization")
            canonical[normalized_key] = _canonicalize(item)
        return canonical
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    raise TypeError(f"Unsupported canonical type: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    canonical = _canonicalize(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    canonical = _canonicalize(value)
    return hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()


def fingerprint_issue(issue: QualityIssue) -> str:
    payload = {
        "version": ISSUE_FINGERPRINT_VERSION,
        "row_number": issue.row_number,
        "instrument_id": issue.instrument_id,
        "symbol": issue.symbol,
        "severity": issue.severity,
        "issue_code": issue.issue_code,
        "field_name": issue.field_name,
        "canonical_raw_value": issue.raw_value,
        "canonical_normalized_value": issue.normalized_value,
    }
    return _sha256(payload)


def fingerprint_preview(payload: dict[str, object]) -> str:
    envelope = {key: value for key, value in payload.items() if key not in _PREVIEW_EXCLUDED_KEYS}
    return _sha256(envelope)
