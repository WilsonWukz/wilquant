from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from quant_lab.backtest.strategy_library import StrategyLibrary, StrategyVersionModel
from quant_lab.datasets.errors import DatasetError

router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    strategy_type: str


class VersionCreate(BaseModel):
    strategy_spec: dict[str, object]
    change_note: str = Field(default="", max_length=2000)


class StrategyDefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    strategy_type: str
    status: str
    created_at: datetime
    updated_at: datetime


class StrategyVersionResponse(BaseModel):
    id: str
    strategy_definition_id: str
    version: int
    strategy_spec: dict[str, object]
    strategy_fingerprint: str
    change_note: str
    created_at: datetime

    @classmethod
    def from_model(cls, model: StrategyVersionModel) -> StrategyVersionResponse:
        return cls(
            id=model.id,
            strategy_definition_id=model.strategy_definition_id,
            version=model.version,
            strategy_spec=json.loads(model.strategy_spec_json),
            strategy_fingerprint=model.strategy_fingerprint,
            change_note=model.change_note,
            created_at=model.created_at,
        )


class StrategyListResponse(BaseModel):
    items: tuple[StrategyDefinitionResponse, ...]


class StrategyVersionListResponse(BaseModel):
    items: tuple[StrategyVersionResponse, ...]


def _library(request: Request) -> StrategyLibrary:
    return StrategyLibrary(request.app.state.sqlite_engine)


def _error(error: DatasetError) -> JSONResponse:
    status_code = {
        "STRATEGY_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "STRATEGY_VERSION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "STRATEGY_ARCHIVED": status.HTTP_409_CONFLICT,
        "STRATEGY_SOURCE_CONFLICT": status.HTTP_409_CONFLICT,
    }.get(error.category, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.category, "message": error.safe_message},
    )


@router.post("", response_model=StrategyDefinitionResponse, status_code=201)
def create(payload: StrategyCreate, request: Request):
    try:
        return _library(request).create_definition(
            payload.name, payload.description, payload.strategy_type
        )
    except DatasetError as error:
        return _error(error)


@router.get("", response_model=StrategyListResponse)
def list_all(request: Request):
    try:
        return StrategyListResponse(
            items=tuple(
                StrategyDefinitionResponse.model_validate(item)
                for item in _library(request).list()
            )
        )
    except DatasetError as error:
        return _error(error)


@router.get("/{strategy_id}", response_model=StrategyDefinitionResponse)
def detail(strategy_id: str, request: Request):
    try:
        return _library(request).get(strategy_id)
    except DatasetError as error:
        return _error(error)


@router.post("/{strategy_id}/versions", response_model=StrategyVersionResponse, status_code=201)
def create_version(strategy_id: str, payload: VersionCreate, request: Request):
    try:
        model = _library(request).create_version(
            strategy_id, payload.strategy_spec, payload.change_note
        )
        return StrategyVersionResponse.from_model(model)
    except DatasetError as error:
        return _error(error)


@router.get("/{strategy_id}/versions", response_model=StrategyVersionListResponse)
def list_versions(strategy_id: str, request: Request):
    try:
        return StrategyVersionListResponse(
            items=tuple(
                StrategyVersionResponse.from_model(item)
                for item in _library(request).versions(strategy_id)
            )
        )
    except DatasetError as error:
        return _error(error)


@router.post("/{strategy_id}/archive", response_model=StrategyDefinitionResponse)
def archive(strategy_id: str, request: Request):
    try:
        return _library(request).archive(strategy_id)
    except DatasetError as error:
        return _error(error)
