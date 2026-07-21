from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ImportInspectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    batch_id: str
    provider_name: str
    columns: tuple[str, ...]
    suggested_mapping: dict[str, str]
    row_count: int
    file_size: int
    source_file_hash: str


class ImportPreviewRequest(BaseModel):
    batch_id: str
    field_mapping: dict[str, str]


class ImportBatchResponse(BaseModel):
    batch_id: str
    provider_name: str
    source_name: str
    source_file_hash: str
    source_file_size: int | None
    status: str
    row_count: int
    accepted_count: int
    rejected_count: int
    warning_count: int
    provider_version: str | None
    schema_version: str
    normalization_version: str | None
    quality_rules_version: str | None
    preview_fingerprint_version: str | None
    preview_fingerprint: str | None
    preview_completed_at: datetime | None
    publish_eligibility: str
    error_category: str | None
    error_summary: str | None


class ImportPreviewResponse(ImportBatchResponse):
    sample_rows: tuple[dict[str, str], ...]


class DataQualityIssueResponse(BaseModel):
    row_number: int | None
    symbol: str | None
    field_name: str | None
    severity: str
    issue_code: str
    message: str
    raw_value: str | None
    normalized_value: str | None
    issue_fingerprint: str
    issue_fingerprint_version: str


class DataQualityIssueListResponse(BaseModel):
    items: tuple[DataQualityIssueResponse, ...]


class ImportErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
    batch_id: str | None = None
    details: dict[str, Any] | None = None
