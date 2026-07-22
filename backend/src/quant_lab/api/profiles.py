from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from quant_lab.api.profile_schemas import (
    ProfileCreateRequest,
    ProfileListResponse,
    ProfileResponse,
    ProfileUpdateRequest,
)
from quant_lab.datasets.errors import DatasetError

router = APIRouter(prefix="/market-data/profiles", tags=["market-data-profiles"])


def _error(error: DatasetError, request_id: str) -> JSONResponse:
    code = (
        404
        if error.category
        in {"PROFILE_NOT_FOUND", "DATASET_VERSION_NOT_FOUND", "CALENDAR_VERSION_NOT_FOUND"}
        else 400
    )
    return JSONResponse(
        status_code=code,
        content={
            "error_code": error.category,
            "message": error.safe_message,
            "request_id": request_id,
        },
    )


@router.post("", response_model=ProfileResponse, status_code=201)
def create_profile(request: Request, payload: ProfileCreateRequest):
    try:
        return request.app.state.profile_service.create_profile(**payload.model_dump())
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.get("", response_model=ProfileListResponse)
def list_profiles(request: Request):
    return ProfileListResponse(
        items=tuple(
            ProfileResponse.model_validate(item)
            for item in request.app.state.profile_repository.list()
        )
    )


@router.get("/{profile_id}", response_model=ProfileResponse)
def get_profile(request: Request, profile_id: str):
    try:
        return request.app.state.profile_repository.get(profile_id)
    except DatasetError as error:
        return _error(error, str(uuid4()))


@router.patch("/{profile_id}", response_model=ProfileResponse)
def update_profile(request: Request, profile_id: str, payload: ProfileUpdateRequest):
    try:
        return request.app.state.profile_service.update_profile(profile_id, **payload.model_dump())
    except DatasetError as error:
        return _error(error, str(uuid4()))
