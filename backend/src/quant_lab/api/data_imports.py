from __future__ import annotations

import logging
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from quant_lab.api.data_schemas import (
    DataQualityIssueListResponse,
    DataQualityIssueResponse,
    ImportBatchResponse,
    ImportInspectionResponse,
    ImportPreviewRequest,
    ImportPreviewResponse,
)
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.staging import ControlledUploadStore, StagedUpload

router = APIRouter(prefix="/data/imports", tags=["data-imports"])
logger = logging.getLogger(__name__)


def _error(error: ImportDataError, request_id: str, batch_id: str | None = None) -> JSONResponse:
    status_code = {
        "FILE_TOO_LARGE": status.HTTP_413_CONTENT_TOO_LARGE,
        "DUPLICATE_SOURCE": status.HTTP_409_CONFLICT,
        "BATCH_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    }.get(error.category, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error.category,
            "message": error.safe_message,
            "request_id": request_id,
            "batch_id": batch_id,
        },
    )


def _server_error(
    error: Exception,
    request_id: str,
    batch_id: str | None = None,
) -> JSONResponse:
    category = "DATABASE_ERROR" if isinstance(error, SQLAlchemyError) else "INTERNAL_ERROR"
    logger.error(
        "Import request failed",
        extra={
            "event": "data_import.failed",
            "request_id": request_id,
            "batch_id": batch_id,
            "error_category": category,
        },
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": category,
            "message": "数据存储暂时不可用" if category == "DATABASE_ERROR" else "导入请求处理失败",
            "request_id": request_id,
            "batch_id": batch_id,
        },
    )


def _discard_unowned_upload(upload: StagedUpload | None) -> None:
    if upload is None:
        return
    try:
        upload.path.unlink(missing_ok=True)
    except OSError:
        logger.error(
            "Failed to discard unowned staged upload",
            extra={"event": "data_import.staging_cleanup_failed"},
        )


def _batch_response(batch: object) -> ImportBatchResponse:
    from quant_lab.market_data.persistence import ImportBatchModel

    assert isinstance(batch, ImportBatchModel)
    replay_metadata = (
        batch.source_file_size,
        batch.field_mapping_json,
        batch.provider_version,
        batch.normalization_version,
        batch.quality_rules_version,
        batch.preview_fingerprint_version,
        batch.preview_fingerprint,
        batch.preview_completed_at,
    )
    publish_eligibility = (
        "ELIGIBLE"
        if batch.status == "PREVIEW_READY" and all(item is not None for item in replay_metadata)
        else "PREVIEW_REQUIRED"
    )
    return ImportBatchResponse(
        batch_id=batch.batch_id,
        provider_name=batch.provider_name,
        source_name=batch.source_name,
        source_file_hash=batch.source_file_hash,
        source_file_size=batch.source_file_size,
        status=batch.status,
        row_count=batch.row_count,
        accepted_count=batch.accepted_count,
        rejected_count=batch.rejected_count,
        warning_count=batch.warning_count,
        provider_version=batch.provider_version,
        schema_version=batch.schema_version,
        normalization_version=batch.normalization_version,
        quality_rules_version=batch.quality_rules_version,
        preview_fingerprint_version=batch.preview_fingerprint_version,
        preview_fingerprint=batch.preview_fingerprint,
        preview_completed_at=batch.preview_completed_at,
        publish_eligibility=publish_eligibility,
        error_category=batch.error_category,
        error_summary=batch.error_summary,
    )


@router.post("/inspect", response_model=ImportInspectionResponse, status_code=201)
async def inspect_import(request: Request, filename: str = Query(min_length=1, max_length=255)):
    request_id = str(uuid4())
    settings = request.app.state.settings
    store = ControlledUploadStore(settings.import_directory, settings.import_max_bytes)
    upload: StagedUpload | None = None
    try:
        upload = await store.stage_stream(filename, request.stream())
        result = request.app.state.import_service.inspect(upload)
        return ImportInspectionResponse(
            batch_id=result.batch_id,
            provider_name=result.inspection.provider_name,
            columns=result.inspection.columns,
            suggested_mapping=result.inspection.suggested_mapping,
            row_count=result.inspection.row_count,
            file_size=result.file_size,
            source_file_hash=result.inspection.sha256,
        )
    except ImportDataError as error:
        _discard_unowned_upload(upload)
        return _error(error, request_id)
    except Exception as error:
        _discard_unowned_upload(upload)
        return _server_error(error, request_id)


@router.post("/preview", response_model=ImportPreviewResponse)
def preview_import(request: Request, payload: ImportPreviewRequest):
    request_id = str(uuid4())
    started = monotonic()
    try:
        result = request.app.state.import_service.preview(payload.batch_id, payload.field_mapping)
        batch = request.app.state.market_data_repository.get_batch(payload.batch_id)
        logger.info(
            "Import preview ready",
            extra={
                "event": "data_import.preview_ready",
                "request_id": request_id,
                "batch_id": batch.batch_id,
                "provider": batch.provider_name,
                "source_hash": batch.source_file_hash,
                "row_count": batch.row_count,
                "accepted_count": batch.accepted_count,
                "rejected_count": batch.rejected_count,
                "warning_count": batch.warning_count,
                "duration_ms": round((monotonic() - started) * 1000),
            },
        )
        response = _batch_response(batch).model_dump()
        return ImportPreviewResponse(**response, sample_rows=result.sample_rows)
    except ImportDataError as error:
        return _error(error, request_id, payload.batch_id)
    except Exception as error:
        return _server_error(error, request_id, payload.batch_id)


@router.get("/{batch_id}", response_model=ImportBatchResponse)
def get_import_batch(request: Request, batch_id: str):
    request_id = str(uuid4())
    try:
        return _batch_response(request.app.state.market_data_repository.get_batch(batch_id))
    except ImportDataError as error:
        return _error(error, request_id, batch_id)
    except Exception as error:
        return _server_error(error, request_id, batch_id)


@router.get("/{batch_id}/issues", response_model=DataQualityIssueListResponse)
def get_import_issues(request: Request, batch_id: str):
    request_id = str(uuid4())
    repository: MarketDataRepository = request.app.state.market_data_repository
    try:
        return DataQualityIssueListResponse(
            items=tuple(
                DataQualityIssueResponse(
                    row_number=item.row_number,
                    symbol=item.symbol,
                    field_name=item.field_name,
                    severity=item.severity,
                    issue_code=item.issue_code,
                    message=item.message,
                    raw_value=item.raw_value,
                    normalized_value=item.normalized_value,
                    issue_fingerprint=item.issue_fingerprint,
                    issue_fingerprint_version=item.issue_fingerprint_version,
                )
                for item in repository.list_issues(batch_id)
            )
        )
    except ImportDataError as error:
        return _error(error, request_id, batch_id)
    except Exception as error:
        return _server_error(error, request_id, batch_id)
