from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from quant_lab.ai.analysis_contracts import (
    ResearchAnalysisRequest,
    ResearchDiagnosis,
    ResearchRecommendation,
)
from quant_lab.ai.analysis_service import ResearchAnalysisService
from quant_lab.ai.contracts import GateResult


class AnalysisRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def safe_handler(request: Request) -> Response:
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(
                    {
                        "error_code": "AI_ANALYSIS_SCHEMA_INVALID",
                        "message": "研究请求不符合固定合同",
                    },
                    status_code=422,
                )

        return safe_handler


router = APIRouter(tags=["ai-research-analysis"], route_class=AnalysisRoute)


class AnalysisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    request: ResearchAnalysisRequest


class AnalysisExecute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    intent: Literal["INITIAL", "RESUME", "RETRY_UNKNOWN"] = "INITIAL"


class AnalysisCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str
    outcome: str | None
    progress: str
    provider_result_unknown: bool
    diagnosis: ResearchDiagnosis | None
    recommendation: ResearchRecommendation | None
    gate: GateResult | None
    attempts: list[dict[str, Any]]
    usage: list[dict[str, Any]]
    provenance: dict[str, Any]
    failure_code: str | None


def _service(request: Request) -> ResearchAnalysisService:
    service = getattr(request.app.state, "ai_analysis_service", None)
    if not isinstance(service, ResearchAnalysisService):
        raise ValueError("AI_ANALYSIS_UNAVAILABLE")
    return service


def _response(service: ResearchAnalysisService, run_id: str) -> AnalysisResponse:
    row = service.analyses.get(run_id)
    run = service.repository.get_run(run_id)
    if run is None:
        raise ValueError("ANALYSIS_NOT_FOUND")

    def accepted(value: str | None) -> Any:
        return service.store.read(json.loads(value)["artifact"]) if value else None

    context = json.loads(row.context_json)
    return AnalysisResponse(
        id=run_id,
        status=run.status,
        outcome=row.outcome,
        progress=row.progress,
        provider_result_unknown=row.provider_result_unknown,
        diagnosis=accepted(row.diagnosis_json),
        recommendation=accepted(row.recommendation_json),
        gate=json.loads(row.gate_json) if row.gate_json else None,
        attempts=[
            {
                "id": a.id,
                "stage": a.stage,
                "status": a.status,
                "parent_attempt_id": a.parent_attempt_id,
                "retry_reason_codes": json.loads(a.retry_reason_codes_json or "[]"),
                "failure_code": a.failure_code,
            }
            for a in service.repository.list_attempts(run_id)
        ],
        usage=[
            {
                "attempt_id": u.attempt_id,
                "prompt_tokens": u.prompt_tokens,
                "completion_tokens": u.completion_tokens,
                "total_tokens": u.total_tokens,
                "estimated_cost": str(u.estimated_cost) if u.estimated_cost is not None else None,
                "currency": u.currency,
            }
            for u in service.repository.list_usage(run_id)
        ],
        provenance={
            "request_fingerprint": row.request_fingerprint,
            "submitted_request_fingerprint": context["submitted_request_fingerprint"],
            "resolved_analysis_input_fingerprint": context["resolved_analysis_input_fingerprint"],
            "knowledge_cutoff_mode": context["knowledge_cutoff_mode"],
            "resolved_knowledge_cutoff": context["resolved_knowledge_cutoff"],
            "market_data_cutoff": context["market_data_cutoff"],
            "evidence_pack_id": context["evidence_pack_id"],
            "evidence_pack_fingerprint": context["evidence_pack_fingerprint"],
            "retrieval_snapshot_id": context["retrieval_snapshot_id"],
            "retrieval_snapshot_fingerprint": context["retrieval_snapshot_fingerprint"],
            "model_config_version_id": run.model_config_version_id,
        },
        failure_code=run.failure_code,
    )


def _error(error: ValueError) -> JSONResponse:
    code = str(error)
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code):
        code = "AI_ANALYSIS_REQUEST_INVALID"
    status = (
        404
        if code == "ANALYSIS_NOT_FOUND"
        else 503
        if code == "AI_ANALYSIS_UNAVAILABLE"
        else 409
        if code
        in {
            "IDEMPOTENCY_KEY_CONFLICT",
            "ANALYSIS_IN_PROGRESS",
            "ANALYSIS_EXECUTE_INTENT_INVALID",
            "PROVIDER_UNKNOWN_CONFIRMATION_REQUIRED",
        }
        else 400
    )
    return JSONResponse(
        {"error_code": code, "message": "研究分析请求未完成。请根据错误代码检查输入或当前状态"},
        status_code=status,
    )


@router.post("/analyses", response_model=AnalysisResponse, status_code=201)
def create_analysis(request: Request, payload: AnalysisCreate) -> AnalysisResponse | JSONResponse:
    """仅冻结研究请求。不调用 Provider。"""
    try:
        service = _service(request)
        row = service.create(payload.request, payload.idempotency_key)
        return _response(service, row.run_id)
    except ValueError as error:
        return _error(error)


@router.post("/analyses/{run_id}/execute", response_model=AnalysisResponse)
def execute_analysis(
    request: Request, run_id: str, payload: AnalysisExecute
) -> AnalysisResponse | JSONResponse:
    """显式同步执行。可能产生 Provider 费用 (may incur provider cost)。未知结果不自动重试。"""
    try:
        service = _service(request)
        service.execute(run_id, payload.idempotency_key, payload.intent)
        return _response(service, run_id)
    except ValueError as error:
        return _error(error)


@router.post("/analyses/{run_id}/cancel", response_model=AnalysisResponse)
def cancel_analysis(
    request: Request, run_id: str, payload: AnalysisCancel
) -> AnalysisResponse | JSONResponse:
    """停止本地编排。不代表上游调用确定未发生。"""
    try:
        service = _service(request)
        service.cancel(run_id)
        return _response(service, run_id)
    except ValueError as error:
        return _error(error)


@router.get("/analyses/{run_id}", response_model=AnalysisResponse)
def get_analysis(request: Request, run_id: str) -> AnalysisResponse | JSONResponse:
    try:
        return _response(_service(request), run_id)
    except ValueError as error:
        return _error(error)
