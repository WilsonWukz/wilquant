from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from quant_lab.datasets.errors import DatasetError
from quant_lab.research.domain import ResearchExperimentStatus

router = APIRouter(prefix="/experiments", tags=["experiments"])

MAX_EXPERIMENT_RUNS = 50


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    hypothesis: str = Field(default="", max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    market_data_profile_id: str | None = None


class ExperimentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    hypothesis: str | None = Field(default=None, max_length=10000)
    tags: list[str] | None = Field(default=None, max_length=32)
    status: Literal["DRAFT", "ACTIVE", "COMPLETED", "ARCHIVED"] | None = None


class RunLinkCreate(BaseModel):
    backtest_run_id: str
    role: Literal["BASELINE", "CANDIDATE", "REFERENCE"]
    label: str | None = Field(default=None, max_length=255)


class RunLinkUpdate(BaseModel):
    role: Literal["BASELINE", "CANDIDATE", "REFERENCE"] | None = None
    label: str | None = Field(default=None, max_length=255)


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    hypothesis: str
    market_data_profile_id: str | None
    status: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class ExperimentListResponse(BaseModel):
    items: tuple[ExperimentResponse, ...]


def _experiment_response(model) -> ExperimentResponse:
    return ExperimentResponse(
        id=model.id,
        name=model.name,
        hypothesis=model.hypothesis,
        market_data_profile_id=model.market_data_profile_id,
        status=model.status,
        tags=json.loads(model.tags_json),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _error(error: DatasetError) -> JSONResponse:
    status_code = {
        "EXPERIMENT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "EXPERIMENT_RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "BACKTEST_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "EXPERIMENT_RUN_DUPLICATE": status.HTTP_409_CONFLICT,
    }.get(error.category, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.category, "message": error.safe_message},
    )


def _repo(request: Request):
    return request.app.state.research_repository


@router.post("", response_model=ExperimentResponse, status_code=201)
def create_experiment(request: Request, payload: ExperimentCreate):
    try:
        model = _repo(request).create_experiment(
            name=payload.name,
            hypothesis=payload.hypothesis,
            tags=payload.tags,
            market_data_profile_id=payload.market_data_profile_id,
        )
        return _experiment_response(model)
    except DatasetError as error:
        return _error(error)


@router.get("", response_model=ExperimentListResponse)
def list_experiments(request: Request, status_filter: str | None = None):
    try:
        return ExperimentListResponse(
            items=tuple(
                _experiment_response(item)
                for item in _repo(request).list_experiments(status=status_filter)
            )
        )
    except DatasetError as error:
        return _error(error)


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(request: Request, experiment_id: str):
    try:
        return _experiment_response(_repo(request).get_experiment(experiment_id))
    except DatasetError as error:
        return _error(error)


@router.patch("/{experiment_id}", response_model=ExperimentResponse)
def update_experiment(request: Request, experiment_id: str, payload: ExperimentUpdate):
    try:
        repo = _repo(request)
        model = repo.get_experiment(experiment_id)
        if (
            model.status
            in (
                ResearchExperimentStatus.ACTIVE.value,
                ResearchExperimentStatus.COMPLETED.value,
            )
            and payload.hypothesis is not None
        ):
            raise DatasetError(
                "EXPERIMENT_HYPOTHESIS_LOCKED", "ACTIVE/COMPLETED 状态不能修改假设"
            )
        values: dict[str, object] = {}
        if payload.name is not None:
            values["name"] = payload.name
        if payload.hypothesis is not None:
            values["hypothesis"] = payload.hypothesis
        if payload.tags is not None:
            values["tags_json"] = json.dumps(payload.tags, ensure_ascii=False, sort_keys=True)
        if payload.status is not None:
            values["status"] = payload.status
        return _experiment_response(repo.update_experiment(experiment_id, values))
    except DatasetError as error:
        return _error(error)


@router.post("/{experiment_id}/runs", status_code=201)
def add_run(request: Request, experiment_id: str, payload: RunLinkCreate):
    try:
        repo = _repo(request)
        repo.get_experiment(experiment_id)
        request.app.state.backtest_repository.get(payload.backtest_run_id)
        links = repo.list_run_links(experiment_id)
        if len(links) >= MAX_EXPERIMENT_RUNS:
            raise DatasetError("EXPERIMENT_RUN_LIMIT", "实验关联回测数量超限")
        model = repo.add_run(experiment_id, payload.backtest_run_id, payload.role, payload.label)
        return {
            "id": model.id,
            "experiment_id": model.experiment_id,
            "backtest_run_id": model.backtest_run_id,
            "role": model.role,
            "label": model.label,
            "created_at": model.created_at,
        }
    except DatasetError as error:
        return _error(error)


@router.patch("/{experiment_id}/runs/{run_id}")
def update_run_link(request: Request, experiment_id: str, run_id: str, payload: RunLinkUpdate):
    try:
        model = _repo(request).update_run_link(experiment_id, run_id, payload.role, payload.label)
        return {
            "id": model.id,
            "experiment_id": model.experiment_id,
            "backtest_run_id": model.backtest_run_id,
            "role": model.role,
            "label": model.label,
        }
    except DatasetError as error:
        return _error(error)


@router.delete("/{experiment_id}/runs/{run_id}", status_code=204)
def remove_run(request: Request, experiment_id: str, run_id: str):
    try:
        _repo(request).remove_run_link(experiment_id, run_id)
        return None
    except DatasetError as error:
        return _error(error)


@router.get("/{experiment_id}/comparison")
def comparison(request: Request, experiment_id: str):
    try:
        repo = _repo(request)
        experiment = repo.get_experiment(experiment_id)
        links = repo.list_run_links(experiment_id)
        runs = tuple(
            request.app.state.backtest_repository.get(link.backtest_run_id) for link in links
        )
        return request.app.state.comparison.compare(experiment, links, runs)
    except DatasetError as error:
        return _error(error)


@router.get("/{experiment_id}/research-report")
def research_report(request: Request, experiment_id: str):
    try:
        repo = _repo(request)
        experiment = repo.get_experiment(experiment_id)
        links = repo.list_run_links(experiment_id)
        runs = tuple(
            request.app.state.backtest_repository.get(link.backtest_run_id) for link in links
        )
        comparison = request.app.state.comparison.compare(experiment, links, runs)
        diagnostics = {}
        strategy_identities = {}
        for run in runs:
            artifacts = request.app.state.backtest_repository.artifacts(run.backtest_run_id)
            diagnostics[run.backtest_run_id] = request.app.state.diagnostics.compute(run, artifacts)
            strategy_identities[run.backtest_run_id] = (
                request.app.state.comparison._strategy_identity(run)
            )
        journal = repo.list_journal_entries(experiment_id=experiment_id)
        return request.app.state.reports.experiment_report(
            experiment, links, runs, comparison, diagnostics, strategy_identities, journal
        )
    except DatasetError as error:
        return _error(error)
