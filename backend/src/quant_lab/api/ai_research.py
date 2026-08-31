from __future__ import annotations

import json

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from quant_lab.ai.cases import ResearchCaseInput
from quant_lab.ai.configuration import AIProvenanceError
from quant_lab.api.ai_research_schemas import (
    AIAnalysisRunCreate,
    AIAnalysisRunResponse,
    AIEvidencePackResponse,
    AIRetrievalSnapshotResponse,
    AITraceEventResponse,
    AITraceListResponse,
    AIUsageListResponse,
    AIUsageResponse,
    AIValidationResultResponse,
    ResearchCaseCreate,
    ResearchCaseResponse,
)

router = APIRouter(tags=["ai-research-provenance"])


def _error(error: AIProvenanceError) -> JSONResponse:
    status_code = {
        "AI_CASE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_RUN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_PROMPT_VERSION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_MODEL_CONFIG_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_EVIDENCE_PACK_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_VALIDATION_RESULT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_RETRIEVAL_SNAPSHOT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "AI_PROVENANCE_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
    }.get(error.category, status.HTTP_400_BAD_REQUEST)
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.category, "message": error.safe_message},
    )


def _require_service(request: Request, name: str):
    service = getattr(request.app.state, name, None)
    if service is None:
        raise AIProvenanceError(
            "AI_PROVENANCE_UNAVAILABLE", "AI provenance 组件当前不可用"
        )
    return service


def _case_response(model) -> ResearchCaseResponse:
    return ResearchCaseResponse(
        id=model.id,
        purpose=model.purpose,
        market=model.market,
        exchange=model.exchange,
        symbol=model.symbol,
        instrument_id=model.instrument_id,
        asset_type=model.asset_type,
        currency=model.currency,
        timeframe=model.timeframe,
        as_of_utc=model.as_of_utc,
        market_local_trade_date=model.market_local_trade_date,
        bindings=json.loads(model.bindings_json),
        previous_case_id=model.previous_case_id,
        previous_analysis_run_id=model.previous_analysis_run_id,
        thesis_revision_id=model.thesis_revision_id,
        fingerprint=model.fingerprint,
        created_by=model.created_by,
        created_at=model.created_at,
    )


def _run_response(model) -> AIAnalysisRunResponse:
    return AIAnalysisRunResponse(
        id=model.id,
        case_id=model.case_id,
        stage=model.stage,
        status=model.status,
        parent_run_id=model.parent_run_id,
        prompt_template_version_id=model.prompt_template_version_id,
        model_config_version_id=model.model_config_version_id,
        case_fingerprint=model.case_fingerprint,
        prompt_template_fingerprint=model.prompt_template_fingerprint,
        resolved_prompt_fingerprint=model.resolved_prompt_fingerprint,
        model_config_fingerprint=model.model_config_fingerprint,
        validator_policy_version=model.validator_policy_version,
        validator_policy_fingerprint=model.validator_policy_fingerprint,
        input_envelope_fingerprint=model.input_envelope_fingerprint,
        raw_response_artifact_sha256=model.raw_response_artifact_sha256,
        normalized_output_fingerprint=model.normalized_output_fingerprint,
        started_at=model.started_at,
        completed_at=model.completed_at,
        failure_code=model.failure_code,
        safe_failure_message=model.safe_failure_message,
        created_at=model.created_at,
    )


@router.post("/research-cases", response_model=ResearchCaseResponse, status_code=201)
def create_research_case(request: Request, payload: ResearchCaseCreate):
    try:
        service = _require_service(request, "ai_case_service")
        return _case_response(
            service.freeze(
                ResearchCaseInput(
                    purpose=payload.purpose,
                    market=payload.market,
                    exchange=payload.exchange,
                    symbol=payload.symbol,
                    instrument_id=payload.instrument_id,
                    asset_type=payload.asset_type,
                    currency=payload.currency,
                    timeframe=payload.timeframe,
                    as_of_utc=payload.as_of_utc,
                    market_local_trade_date=payload.market_local_trade_date,
                    bindings=payload.bindings,
                    previous_case_id=payload.previous_case_id,
                    previous_analysis_run_id=payload.previous_analysis_run_id,
                    thesis_revision_id=payload.thesis_revision_id,
                ),
                actor="USER",
            )
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get("/research-cases/{case_id}", response_model=ResearchCaseResponse)
def get_research_case(request: Request, case_id: str):
    try:
        repository = _require_service(request, "ai_repository")
        model = repository.get_research_case(case_id)
        if model is None:
            raise AIProvenanceError("AI_CASE_NOT_FOUND", "研究案例不存在")
        return _case_response(model)
    except AIProvenanceError as error:
        return _error(error)


@router.post("/ai-analysis-runs", response_model=AIAnalysisRunResponse, status_code=201)
def create_analysis_run(request: Request, payload: AIAnalysisRunCreate):
    try:
        service = _require_service(request, "ai_provenance_service")
        return _run_response(
            service.create_run(
                case_id=payload.case_id,
                stage=payload.stage,
                prompt_template_version_id=payload.prompt_template_version_id,
                model_config_version_id=payload.model_config_version_id,
                resolved_prompt_fingerprint=payload.resolved_prompt_fingerprint,
                validator_policy_version=payload.validator_policy_version,
                validator_policy_fingerprint=payload.validator_policy_fingerprint,
                parent_run_id=payload.parent_run_id,
            )
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get("/ai-analysis-runs/{run_id}", response_model=AIAnalysisRunResponse)
def get_analysis_run(request: Request, run_id: str):
    try:
        service = _require_service(request, "ai_provenance_service")
        return _run_response(service.get_run(run_id))
    except AIProvenanceError as error:
        return _error(error)


@router.get("/ai-analysis-runs/{run_id}/trace", response_model=AITraceListResponse)
def get_analysis_trace(request: Request, run_id: str):
    try:
        service = _require_service(request, "ai_provenance_service")
        return AITraceListResponse(
            items=tuple(
                AITraceEventResponse(
                    id=item.id,
                    run_id=item.run_id,
                    sequence=item.sequence,
                    event_type=item.event_type,
                    payload=json.loads(item.payload_json),
                    payload_fingerprint=item.payload_fingerprint,
                    occurred_at=item.occurred_at,
                )
                for item in service.list_trace(run_id)
            )
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get("/ai-analysis-runs/{run_id}/usage", response_model=AIUsageListResponse)
def get_analysis_usage(request: Request, run_id: str):
    try:
        service = _require_service(request, "ai_provenance_service")
        return AIUsageListResponse(
            items=tuple(
                AIUsageResponse(
                    id=item.id,
                    run_id=item.run_id,
                    attempt_id=item.attempt_id,
                    prompt_tokens=item.prompt_tokens,
                    cached_prompt_tokens=item.cached_prompt_tokens,
                    completion_tokens=item.completion_tokens,
                    total_tokens=item.total_tokens,
                    reported_cost=item.reported_cost,
                    estimated_cost=item.estimated_cost,
                    currency=item.currency,
                    is_estimate=item.is_estimate,
                    occurred_at=item.occurred_at,
                )
                for item in service.list_usage(run_id)
            )
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get("/ai/evidence-packs/{pack_id}", response_model=AIEvidencePackResponse)
def get_evidence_pack(request: Request, pack_id: str):
    try:
        repository = _require_service(request, "ai_repository")
        model = repository.get_evidence_pack(pack_id)
        if model is None:
            raise AIProvenanceError(
                "AI_EVIDENCE_PACK_NOT_FOUND", "EvidencePack 不存在"
            )
        return AIEvidencePackResponse(
            id=model.id,
            case_id=model.case_id,
            temporal_context=json.loads(model.temporal_context_json),
            evidence_context=json.loads(model.evidence_context_json),
            requirements=json.loads(model.requirements_json),
            items=tuple(json.loads(model.items_json)),
            policy_version=model.policy_version,
            fingerprint=model.fingerprint,
            created_at=model.created_at,
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get(
    "/ai/validation-results/{result_id}", response_model=AIValidationResultResponse
)
def get_validation_result(request: Request, result_id: str):
    try:
        repository = _require_service(request, "ai_repository")
        model = repository.get_validation_result(result_id)
        if model is None:
            raise AIProvenanceError(
                "AI_VALIDATION_RESULT_NOT_FOUND", "ValidationResult 不存在"
            )
        return AIValidationResultResponse(
            id=model.id,
            run_id=model.run_id,
            attempt_id=model.attempt_id,
            evidence_pack_id=model.evidence_pack_id,
            disposition=model.disposition,
            findings=tuple(json.loads(model.findings_json)),
            accepted_assertions=tuple(json.loads(model.accepted_assertions_json)),
            observations=tuple(json.loads(model.observations_json)),
            candidate_fingerprint=model.candidate_fingerprint,
            policy_version=model.policy_version,
            fingerprint=model.fingerprint,
            created_at=model.created_at,
        )
    except AIProvenanceError as error:
        return _error(error)


@router.get(
    "/ai/retrieval-snapshots/{snapshot_id}",
    response_model=AIRetrievalSnapshotResponse,
)
def get_retrieval_snapshot(request: Request, snapshot_id: str):
    try:
        repository = _require_service(request, "ai_repository")
        model = repository.get_retrieval_snapshot(snapshot_id)
        if model is None:
            raise AIProvenanceError(
                "AI_RETRIEVAL_SNAPSHOT_NOT_FOUND", "RetrievalSnapshot 不存在"
            )
        return AIRetrievalSnapshotResponse(
            id=model.id,
            query=json.loads(model.query_json),
            policy_version=model.policy_version,
            candidates=tuple(json.loads(model.candidates_json)),
            exclusions=tuple(json.loads(model.exclusions_json)),
            fingerprint=model.fingerprint,
            created_at=model.created_at,
        )
    except AIProvenanceError as error:
        return _error(error)
