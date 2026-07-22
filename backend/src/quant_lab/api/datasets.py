from __future__ import annotations

import logging
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from quant_lab.api.dataset_schemas import (
    DatasetCreateRequest,
    DatasetListResponse,
    DatasetPublishRequest,
    DatasetResponse,
    DatasetVersionListResponse,
    DatasetVersionResponse,
)
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.publication import PublicationService
from quant_lab.datasets.repository import DatasetIdentity, DatasetRepository

router = APIRouter(prefix="/datasets", tags=["datasets"])
publish_router = APIRouter(prefix="/data-batches", tags=["datasets"])
logger = logging.getLogger(__name__)


def _repository(request: Request) -> DatasetRepository:
    repository: DatasetRepository = request.app.state.dataset_repository
    return repository


def _publication(request: Request) -> PublicationService:
    return request.app.state.publication_service


def _query(request: Request):
    return request.app.state.dataset_query_service


def _error(error: DatasetError, request_id: str) -> JSONResponse:
    status_code = {
        "DATASET_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "DATASET_VERSION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "DATASET_IDENTITY_CONFLICT": status.HTTP_409_CONFLICT,
    }.get(error.category, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error.category,
            "message": error.safe_message,
            "request_id": request_id,
        },
    )


def _server_error(error: Exception, request_id: str) -> JSONResponse:
    category = "DATABASE_ERROR" if isinstance(error, SQLAlchemyError) else "INTERNAL_ERROR"
    logger.error(
        "Dataset request failed",
        extra={"event": "dataset.request_failed", "request_id": request_id, "category": category},
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error_code": category,
            "message": (
                "数据存储暂时不可用" if category == "DATABASE_ERROR" else "数据集请求处理失败"
            ),
            "request_id": request_id,
        },
    )


@router.post("", response_model=DatasetResponse)
def create_dataset(
    request: Request,
    response: Response,
    payload: DatasetCreateRequest,
):
    request_id = str(uuid4())
    try:
        result = _repository(request).create_or_get(
            DatasetIdentity(
                logical_key=payload.logical_key,
                dataset_type=payload.dataset_type,
                market=payload.market,
                frequency=payload.frequency,
                adjustment_type=payload.adjustment_type,
                schema_version=payload.schema_version,
            ),
            name=payload.name,
            description=payload.description,
        )
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        return DatasetResponse.model_validate(result.dataset)
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)


@router.get("", response_model=DatasetListResponse)
def list_datasets(request: Request):
    request_id = str(uuid4())
    try:
        return DatasetListResponse(
            items=tuple(
                DatasetResponse.model_validate(dataset)
                for dataset in _repository(request).list_datasets()
            )
        )
    except Exception as error:
        return _server_error(error, request_id)


@router.get("/{dataset_id}/versions", response_model=DatasetVersionListResponse)
def list_dataset_versions(request: Request, dataset_id: str):
    request_id = str(uuid4())
    try:
        return DatasetVersionListResponse(
            items=tuple(
                DatasetVersionResponse.model_validate(version)
                for version in _repository(request).list_versions(dataset_id)
            )
        )
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)


@router.get(
    "/{dataset_id}/versions/{version_id}",
    response_model=DatasetVersionResponse,
)
def get_dataset_version(request: Request, dataset_id: str, version_id: str):
    request_id = str(uuid4())
    try:
        return DatasetVersionResponse.model_validate(
            _repository(request).get_version(dataset_id, version_id)
        )
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)


@publish_router.post("/{batch_id}/publish")
def publish_batch(request: Request, batch_id: str, payload: DatasetPublishRequest):
    request_id = str(uuid4())
    if payload.import_batch_id != batch_id:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "BATCH_ID_MISMATCH",
                "message": "import batch mismatch",
                "request_id": request_id,
            },
        )
    if not payload.confirm_publish:
        return JSONResponse(
            status_code=400,
            content={
                "error_code": "PUBLISH_CONFIRMATION_REQUIRED",
                "message": "publish confirmation required",
                "request_id": request_id,
            },
        )
    try:
        version = _publication(request).publish(
            dataset_id=payload.dataset_id,
            batch_id=batch_id,
            expected_preview_fingerprint=payload.expected_preview_fingerprint,
            confirm_warnings=payload.confirm_warnings,
            request_id=request_id,
            frequency=payload.frequency,
            adjustment_type=payload.adjustment_type,
            operator_label=payload.operator_label,
            request_note=payload.request_note,
        )
        return DatasetVersionResponse.model_validate(version)
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)


@router.get("/{dataset_id}/versions/{version_id}/summary")
def dataset_summary(request: Request, dataset_id: str, version_id: str):
    request_id = str(uuid4())
    try:
        return _query(request).summary(dataset_id, version_id)
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)


@router.get("/{dataset_id}/versions/{version_id}/bars")
def dataset_bars(
    request: Request,
    dataset_id: str,
    version_id: str,
    instrument_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
):
    request_id = str(uuid4())
    try:
        return {
            "items": _query(request).bars(
                dataset_id,
                version_id,
                instrument_id=instrument_id,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            ),
            "limit": limit,
            "offset": offset,
        }
    except DatasetError as error:
        return _error(error, request_id)
    except Exception as error:
        return _server_error(error, request_id)
