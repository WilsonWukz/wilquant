from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DatasetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logical_key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    dataset_type: str = Field(min_length=1, max_length=32)
    market: str = Field(min_length=1, max_length=32)
    frequency: str = Field(min_length=1, max_length=32)
    adjustment_type: str = Field(min_length=1, max_length=32)
    schema_version: str = Field(min_length=1, max_length=64)


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_id: str
    dataset_key: str
    logical_key: str
    name: str
    description: str | None
    dataset_type: str
    market: str
    frequency: str
    adjustment_type: str
    schema_version: str
    created_at: datetime
    updated_at: datetime
    is_active: bool


class DatasetListResponse(BaseModel):
    items: tuple[DatasetResponse, ...]


class DatasetVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_version_id: str
    dataset_id: str
    version: int
    status: str
    source_batch_id: str
    source_preview_fingerprint: str
    publication_fingerprint: str
    schema_version: str
    normalization_version: str
    quality_rules_version: str
    publication_format_version: str
    partition_strategy_version: str
    row_count: int
    instrument_count: int
    min_timestamp: datetime | None
    max_timestamp: datetime | None
    partition_count: int
    file_count: int
    total_size_bytes: int
    quality_issue_count: int
    warning_count: int
    blocking_issue_count: int
    quality_summary_json: str | None
    relative_version_root: str | None
    manifest_path: str | None
    manifest_sha256: str | None
    publication_claimed_at: datetime
    published_at: datetime | None
    created_at: datetime
    failure_code: str | None
    failure_reason: str | None


class DatasetVersionListResponse(BaseModel):
    items: tuple[DatasetVersionResponse, ...]


class DatasetErrorResponse(BaseModel):
    error_code: str
    message: str
    request_id: str
