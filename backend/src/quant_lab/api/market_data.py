from __future__ import annotations

from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from quant_lab.datasets.errors import DatasetError

router = APIRouter(prefix="/market-data/profiles", tags=["market-data"])


def _error(error: DatasetError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error_code": error.category,
            "message": error.safe_message,
            "request_id": request_id,
        },
    )


@router.get("/{profile_id}/instruments")
def instruments(request: Request, profile_id: str):
    try:
        return {"items": request.app.state.market_data_service.instruments(profile_id)}
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("/{profile_id}/bars")
def bars(
    request: Request,
    profile_id: str,
    instrument_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 100,
    offset: int = 0,
):
    try:
        return request.app.state.market_data_service.bars(
            profile_id,
            instrument_id=instrument_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("/{profile_id}/coverage")
def coverage(
    request: Request,
    profile_id: str,
    instrument_id: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = 1000,
):
    try:
        return request.app.state.market_data_service.coverage(
            profile_id, instrument_id=instrument_id, start=start, end=end, limit=limit
        )
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("/{profile_id}/health")
def health(request: Request, profile_id: str):
    try:
        return request.app.state.market_data_service.health(profile_id)
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("/{profile_id}/snapshot")
def snapshot(request: Request, profile_id: str):
    try:
        return request.app.state.market_data_service.snapshot(profile_id)
    except DatasetError as error:
        return _error(error, str(uuid4()))
