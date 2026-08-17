from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from quant_lab.api.backtest_schemas import (
    BacktestCreateRequest,
    BacktestListResponse,
    BacktestResponse,
)
from quant_lab.datasets.errors import DatasetError

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _error(error: DatasetError) -> JSONResponse:
    code = (
        404
        if error.category in {"BACKTEST_NOT_FOUND", "BACKTEST_ARTIFACT_NOT_FOUND"}
        else 409
        if error.category in {"RUN_NOT_SUCCEEDED", "ARTIFACT_INTEGRITY_FAILURE"}
        else 400
    )
    return JSONResponse(
        status_code=code, content={"error_code": error.category, "message": error.safe_message}
    )


@router.post("", response_model=BacktestResponse, status_code=201)
def create_backtest(request: Request, payload: BacktestCreateRequest):
    try:
        config = {
            "fee_policy": payload.fee_policy,
            "slippage_policy": payload.slippage_policy,
            "max_volume_participation": payload.max_volume_participation,
            "instrument_metadata_overrides": payload.instrument_metadata_overrides,
        }
        return request.app.state.backtest_service.create_run(
            **payload.model_dump(
                exclude={
                    "fee_policy",
                    "slippage_policy",
                    "max_volume_participation",
                    "instrument_metadata_overrides",
                }
            ),
            config=config,
        )
    except DatasetError as error:
        return _error(error)


@router.get("", response_model=BacktestListResponse)
def list_backtests(request: Request):
    return BacktestListResponse(
        items=tuple(
            BacktestResponse.model_validate(item)
            for item in request.app.state.backtest_repository.list_runs()
        )
    )


@router.get("/{run_id}", response_model=BacktestResponse)
def get_backtest(request: Request, run_id: str):
    try:
        return request.app.state.backtest_repository.get(run_id)
    except DatasetError as error:
        return _error(error)


@router.get("/{run_id}/metrics")
@router.get("/{run_id}/equity")
@router.get("/{run_id}/orders")
@router.get("/{run_id}/fills")
@router.get("/{run_id}/positions")
@router.get("/{run_id}/{artifact_type}")
def get_artifact(request: Request, run_id: str, artifact_type: str | None = None):
    try:
        artifact_type = artifact_type or request.url.path.rsplit("/", 1)[-1]
        run = request.app.state.backtest_repository.get(run_id)
        artifact = next(
            (
                item
                for item in request.app.state.backtest_repository.artifacts(run_id)
                if item.artifact_type == artifact_type.upper()
            ),
            None,
        )
        if artifact is None:
            raise DatasetError("BACKTEST_ARTIFACT_NOT_FOUND", "回测产物不存在")
        path = request.app.state.settings.runtime_root / artifact.relative_path
        return {
            "run_id": run.backtest_run_id,
            "artifact_type": artifact.artifact_type,
            "relative_path": artifact.relative_path,
            "sha256": artifact.sha256,
            "size_bytes": artifact.size_bytes,
            "row_count": artifact.row_count,
            "path_exists": path.exists(),
        }
    except DatasetError as error:
        return _error(error)


@router.get("/{run_id}/diagnostics")
def get_diagnostics(request: Request, run_id: str):
    try:
        run = request.app.state.backtest_repository.get(run_id)
        if run.status != "SUCCEEDED":
            raise DatasetError("RUN_NOT_SUCCEEDED", "回测未成功完成")
        artifacts = request.app.state.backtest_repository.artifacts(run_id)
        return request.app.state.diagnostics.compute(run, artifacts)
    except DatasetError as error:
        return _error(error)


@router.get("/{run_id}/research-report")
def get_research_report(request: Request, run_id: str):
    try:
        run = request.app.state.backtest_repository.get(run_id)
        strategy_identity = request.app.state.comparison._strategy_identity(run)
        return request.app.state.reports.run_report(run, strategy_identity)
    except DatasetError as error:
        return _error(error)
