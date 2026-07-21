from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast

from quant_lab.market_data.domain import ImportBatchStatus, PreviewRecord
from quant_lab.market_data.persistence import ImportBatchModel


class PublicationEligibility(StrEnum):
    PREVIEW_REQUIRED = "PREVIEW_REQUIRED"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    WARNING_CONFIRMATION_REQUIRED = "WARNING_CONFIRMATION_REQUIRED"
    ELIGIBLE = "ELIGIBLE"


_PUBLISHABLE_OR_REPLAYABLE_STATUSES = frozenset(
    {
        ImportBatchStatus.PREVIEW_READY.value,
        ImportBatchStatus.PUBLISHING.value,
        ImportBatchStatus.PUBLISHED.value,
        ImportBatchStatus.PUBLISH_FAILED.value,
    }
)


def evaluate_publication_eligibility(
    *,
    status: str,
    preview: PreviewRecord | None,
    issue_severities: Iterable[str],
    confirm_warnings: bool,
) -> PublicationEligibility:
    """Pure publication gate shared by API display and atomic claim."""
    if status not in _PUBLISHABLE_OR_REPLAYABLE_STATUSES or preview is None:
        return PublicationEligibility.PREVIEW_REQUIRED

    severities = frozenset(issue_severities)
    if (
        preview.accepted_count <= 0
        or preview.rejected_count > 0
        or bool(severities & {"ERROR", "FATAL"})
    ):
        return PublicationEligibility.QUALITY_BLOCKED
    if (preview.warning_count > 0 or "WARNING" in severities) and not confirm_warnings:
        return PublicationEligibility.WARNING_CONFIRMATION_REQUIRED
    return PublicationEligibility.ELIGIBLE


def preview_record_from_batch(batch: ImportBatchModel) -> PreviewRecord:
    """Restore SQLite UTC semantics and validate all persisted Preview metadata."""
    completed_at = batch.preview_completed_at
    if not isinstance(completed_at, datetime):
        raise ValueError("Persisted Preview completion time is missing or invalid")
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    elif completed_at.utcoffset() != timedelta(0):
        raise ValueError("Persisted Preview completion time must be UTC")

    return PreviewRecord(
        source_file_size=cast(int, batch.source_file_size),
        field_mapping_json=cast(str, batch.field_mapping_json),
        provider_version=cast(str, batch.provider_version),
        schema_version=batch.schema_version,
        normalization_version=cast(str, batch.normalization_version),
        quality_rules_version=cast(str, batch.quality_rules_version),
        preview_fingerprint_version=cast(str, batch.preview_fingerprint_version),
        row_count=batch.row_count,
        accepted_count=batch.accepted_count,
        rejected_count=batch.rejected_count,
        warning_count=batch.warning_count,
        preview_fingerprint=cast(str, batch.preview_fingerprint),
        preview_completed_at=completed_at,
        issues=(),
    )


def persisted_publication_eligibility(
    batch: ImportBatchModel,
    *,
    issue_severities: Iterable[str],
    confirm_warnings: bool,
) -> PublicationEligibility:
    try:
        preview = preview_record_from_batch(batch)
    except (TypeError, ValueError):
        preview = None
    return evaluate_publication_eligibility(
        status=batch.status,
        preview=preview,
        issue_severities=issue_severities,
        confirm_warnings=confirm_warnings,
    )
