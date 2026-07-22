from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from quant_lab.api.calendar_schemas import (
    CalendarCreateRequest,
    CalendarListResponse,
    CalendarResponse,
    CalendarSessionListResponse,
    CalendarSessionResponse,
    CalendarVersionListResponse,
    CalendarVersionResponse,
)
from quant_lab.datasets.errors import DatasetError
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository
from quant_lab.market_data.staging import ControlledUploadStore

router = APIRouter(prefix="/market-calendars", tags=["market-calendars"])


def _repository(request: Request) -> TradingCalendarRepository:
    return request.app.state.calendar_repository


def _error(error: DatasetError, request_id: str) -> JSONResponse:
    code = 404 if error.category in {"CALENDAR_NOT_FOUND", "CALENDAR_VERSION_NOT_FOUND"} else 400
    return JSONResponse(
        status_code=code,
        content={
            "error_code": error.category,
            "message": error.safe_message,
            "request_id": request_id,
        },
    )


@router.post("", response_model=CalendarResponse, status_code=status.HTTP_201_CREATED)
def create_calendar(request: Request, payload: CalendarCreateRequest):
    try:
        return _repository(request).create_calendar(**payload.model_dump())
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("", response_model=CalendarListResponse)
def list_calendars(request: Request):
    return CalendarListResponse(
        items=tuple(
            CalendarResponse.model_validate(item) for item in _repository(request).list_calendars()
        )
    )


@router.post(
    "/{calendar_id}/versions/import",
    response_model=CalendarVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_calendar(
    request: Request, calendar_id: str, filename: str = Query(min_length=1, max_length=255)
):
    request_id = str(uuid4())
    settings = request.app.state.settings
    store = ControlledUploadStore(settings.import_directory, settings.import_max_bytes)
    upload = None
    try:
        upload = await store.stage_stream(filename, request.stream())
        result = request.app.state.calendar_import_service.import_csv(
            calendar_id=calendar_id, path=upload.path
        )
        upload.path.unlink(missing_ok=True)
        return result
    except DatasetError as error:
        if upload is not None:
            upload.path.unlink(missing_ok=True)
        return _error(error, request_id)


@router.get("/{calendar_id}/versions", response_model=CalendarVersionListResponse)
def list_versions(request: Request, calendar_id: str):
    try:
        return CalendarVersionListResponse(
            items=tuple(
                CalendarVersionResponse.model_validate(item)
                for item in _repository(request).list_versions(calendar_id)
            )
        )
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("/{calendar_id}/versions/{version_id}", response_model=CalendarVersionResponse)
def get_version(request: Request, calendar_id: str, version_id: str):
    try:
        return _repository(request).get_version(calendar_id, version_id)
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get(
    "/{calendar_id}/versions/{version_id}/sessions", response_model=CalendarSessionListResponse
)
def list_sessions(
    request: Request,
    calendar_id: str,
    version_id: str,
    start: date | None = None,
    end: date | None = None,
    open_only: bool = False,
    limit: int = 1000,
    offset: int = 0,
):
    try:
        _repository(request).get_version(calendar_id, version_id)
        return CalendarSessionListResponse(
            items=tuple(
                CalendarSessionResponse.model_validate(item)
                for item in _repository(request).list_sessions(
                    version_id,
                    start=start,
                    end=end,
                    open_only=open_only,
                    limit=limit,
                    offset=offset,
                )
            )
        )
    except DatasetError as error:
        return _error(error, str(uuid4()))
