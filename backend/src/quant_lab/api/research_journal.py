from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from quant_lab.datasets.errors import DatasetError

router = APIRouter(prefix="/research-journal", tags=["research-journal"])

_ENTRY_TYPES = ("HYPOTHESIS", "OBSERVATION", "DECISION", "CONCLUSION", "TODO")


class JournalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    entry_type: Literal["HYPOTHESIS", "OBSERVATION", "DECISION", "CONCLUSION", "TODO"]
    content: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    experiment_id: str | None = None
    backtest_run_id: str | None = None
    strategy_version_id: str | None = None


class JournalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    entry_type: Literal["HYPOTHESIS", "OBSERVATION", "DECISION", "CONCLUSION", "TODO"] | None = None
    content: str | None = Field(default=None, max_length=50000)
    tags: list[str] | None = Field(default=None, max_length=32)


def _entry_response(model) -> dict[str, object]:
    return {
        "id": model.id,
        "title": model.title,
        "entry_type": model.entry_type,
        "content": model.content,
        "tags": json.loads(model.tags_json),
        "experiment_id": model.experiment_id,
        "backtest_run_id": model.backtest_run_id,
        "strategy_version_id": model.strategy_version_id,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
    }


def _error(error: DatasetError) -> JSONResponse:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if error.category == "JOURNAL_ENTRY_NOT_FOUND"
        else status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.category, "message": error.safe_message},
    )


def _repo(request: Request):
    return request.app.state.research_repository


@router.post("", status_code=201)
def create_entry(request: Request, payload: JournalCreate):
    try:
        model = _repo(request).create_journal_entry(
            title=payload.title,
            entry_type=payload.entry_type,
            content=payload.content,
            tags=payload.tags,
            experiment_id=payload.experiment_id,
            backtest_run_id=payload.backtest_run_id,
            strategy_version_id=payload.strategy_version_id,
        )
        return _entry_response(model)
    except DatasetError as error:
        return _error(error)


@router.get("")
def list_entries(
    request: Request,
    entry_type: str | None = None,
    experiment_id: str | None = None,
    backtest_run_id: str | None = None,
    strategy_version_id: str | None = None,
    tag: str | None = None,
):
    try:
        items = _repo(request).list_journal_entries(
            entry_type=entry_type,
            experiment_id=experiment_id,
            backtest_run_id=backtest_run_id,
            strategy_version_id=strategy_version_id,
            tag=tag,
        )
        return {"items": [_entry_response(item) for item in items]}
    except DatasetError as error:
        return _error(error)


@router.get("/{entry_id}")
def get_entry(request: Request, entry_id: str):
    try:
        return _entry_response(_repo(request).get_journal_entry(entry_id))
    except DatasetError as error:
        return _error(error)


@router.patch("/{entry_id}")
def update_entry(request: Request, entry_id: str, payload: JournalUpdate):
    try:
        model = _repo(request).update_journal_entry(
            entry_id,
            title=payload.title,
            entry_type=payload.entry_type,
            content=payload.content,
            tags=payload.tags,
        )
        return _entry_response(model)
    except DatasetError as error:
        return _error(error)


@router.delete("/{entry_id}", status_code=204)
def delete_entry(request: Request, entry_id: str):
    try:
        _repo(request).delete_journal_entry(entry_id)
        return None
    except DatasetError as error:
        return _error(error)
