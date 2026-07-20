from __future__ import annotations

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
    status: str
    row_count: int
    accepted_count: int
    rejected_count: int
    warning_count: int
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


class DataQualityIssueListResponse(BaseModel):
    items: tuple[DataQualityIssueResponse, ...]


class ImportErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
    batch_id: str | None = None
    details: dict[str, Any] | None = None
