from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from quant_lab.backtest.strategy_library import StrategyLibrary

router = APIRouter(prefix="/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    strategy_type: str


class VersionCreate(BaseModel):
    strategy_spec: dict[str, object]
    change_note: str = Field(default="", max_length=2000)


def _library(request: Request) -> StrategyLibrary:
    return StrategyLibrary(request.app.state.sqlite_engine)


@router.post("")
def create(payload: StrategyCreate, request: Request):
    return _library(request).create_definition(
        payload.name, payload.description, payload.strategy_type
    )


@router.get("")
def list_all(request: Request):
    return {"items": _library(request).list()}


@router.get("/{strategy_id}")
def detail(strategy_id: str, request: Request):
    return _library(request).get(strategy_id)


@router.post("/{strategy_id}/versions")
def create_version(strategy_id: str, payload: VersionCreate, request: Request):
    return _library(request).create_version(strategy_id, payload.strategy_spec, payload.change_note)


@router.get("/{strategy_id}/versions")
def list_versions(strategy_id: str, request: Request):
    return {"items": _library(request).versions(strategy_id)}


@router.post("/{strategy_id}/archive")
def archive(strategy_id: str, request: Request):
    return _library(request).archive(strategy_id)
