from __future__ import annotations

import json
from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_lab.api.paper_schemas import (
    AdvanceRequest,
    AuditEventList,
    AuditEventResponse,
    CancelOrderRequest,
    EquityPointResponse,
    EquitySeries,
    LifecycleRequest,
    ManualIntentCreate,
    ManualIntentResponse,
    PaperAccountCreate,
    PaperAccountList,
    PaperAccountResponse,
    PaperAdvanceResponse,
    PaperFillList,
    PaperFillResponse,
    PaperOrderList,
    PaperOrderResponse,
    PaperPositionList,
    PaperPositionResponse,
    PaperSessionCreate,
    PaperSessionList,
    PaperSessionResponse,
    RiskDecisionList,
    RiskDecisionResponse,
    RiskPolicyCreate,
    RiskPolicyPatch,
    RiskPolicyResponse,
)
from quant_lab.datasets.errors import DatasetError
from quant_lab.market_data.persistence import InstrumentModel
from quant_lab.paper.errors import PaperError
from quant_lab.paper.models import (
    PaperAccountModel,
    PaperAccountSnapshotModel,
    PaperAuditEventModel,
    PaperFillModel,
    PaperOrderIntentModel,
    PaperOrderModel,
    PaperPositionModel,
    PaperRiskDecisionModel,
    PaperRiskPolicyModel,
    PaperRiskPolicyVersionModel,
    PaperSessionModel,
)
from quant_lab.paper.service import AdvanceSessionRequest

router = APIRouter(prefix="/paper", tags=["paper"])

_ERROR_STATUS: dict[str, int] = {
    "PAPER_ACCOUNT_NOT_FOUND": 404,
    "PAPER_SESSION_NOT_FOUND": 404,
    "PAPER_ORDER_NOT_FOUND": 404,
    "PAPER_INTENT_NOT_FOUND": 404,
    "RISK_POLICY_NOT_FOUND": 404,
    "RISK_POLICY_VERSION_NOT_FOUND": 404,
    "STRATEGY_VERSION_NOT_FOUND": 404,
    "CALENDAR_NOT_FOUND": 404,
    "CALENDAR_VERSION_NOT_FOUND": 404,
    "PROFILE_NOT_FOUND": 404,
    "SESSION_STATE_TRANSITION_INVALID": 409,
    "SESSION_NOT_RUNNING": 409,
    "SESSION_NOT_STARTED": 409,
    "SESSION_VERSION_CONFLICT": 409,
    "ORDER_STATE_TRANSITION_INVALID": 409,
    "ORDER_STATE_CONFLICT": 409,
    "IDEMPOTENCY_KEY_CONFLICT": 409,
    "RISK_POLICY_ALREADY_ACTIVE": 409,
    "FREEZE_NOT_AUTHORIZED": 409,
    "UNFREEZE_NOT_AUTHORIZED": 409,
    "NO_FUTURE_SESSION": 409,
    "ADVANCE_IN_PROGRESS": 409,
    "REPLAY_RANGE_INVALID": 400,
    "INITIAL_CASH_INVALID": 400,
    "RISK_POLICY_INVALID": 400,
    "INVALID_QUERY_LIMIT": 400,
    "STRATEGY_UNSUPPORTED": 400,
    "STRATEGY_SPEC_INVALID": 400,
    "ADVANCE_FAILED": 500,
    "CORRUPT_ORDER_RISK_DECISION": 500,
    "NEGATIVE_CASH": 500,
    "POSITION_MISSING": 500,
    "LOT_MISSING": 500,
    "RISK_DECISION_NOT_APPROVED": 500,
    "RISK_ENGINE_ERROR": 500,
    "STRATEGY_ERROR": 500,
    "PAPER_INTERNAL_ERROR": 500,
}


def _error(error: Exception) -> JSONResponse:
    if isinstance(error, PaperError):
        code, message = error.code, error.message
    elif isinstance(error, DatasetError):
        code, message = error.category, error.safe_message
    else:
        code, message = "PAPER_INTERNAL_ERROR", "paper 内部错误"
    status_code = _ERROR_STATUS.get(code, 400)
    return JSONResponse(status_code=status_code, content={"error_code": code, "message": message})


def _session_service(request: Request):
    return request.app.state.paper_session_service


def _repository(request: Request):
    return request.app.state.paper_repository


def _policy_service(request: Request):
    return request.app.state.paper_risk_policy_service


def _risk_service(request: Request):
    return request.app.state.paper_risk_service


# --- serializers ---


def _account_response(model: PaperAccountModel) -> PaperAccountResponse:
    return PaperAccountResponse(
        id=model.id,
        name=model.name,
        status=model.status,
        base_currency=model.base_currency,
        initial_cash=model.initial_cash,
        cash=model.cash,
        market_value=model.market_value,
        account_equity=model.account_equity,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _session_response(model: PaperSessionModel) -> PaperSessionResponse:
    snapshot = cast(dict[str, object], json.loads(model.market_data_snapshot_json))
    exec_config = cast(dict[str, object], json.loads(model.execution_config_json))
    dataset_version = snapshot.get("bars_dataset_version_id")
    calendar_version = snapshot.get("calendar_version_id")
    return PaperSessionResponse(
        id=model.id,
        name=model.name,
        paper_account_id=model.paper_account_id,
        market_data_profile_id=model.market_data_profile_id,
        market_data_snapshot_fingerprint=model.market_data_snapshot_fingerprint,
        strategy_version_id=model.strategy_version_id,
        status=model.status,
        replay_start_date=model.replay_start_date,
        replay_end_date=model.replay_end_date,
        current_session_date=model.current_session_date,
        version=model.version,
        execution_config=exec_config,
        execution_config_fingerprint=model.execution_config_fingerprint,
        dataset_version_id=str(dataset_version) if dataset_version is not None else None,
        calendar_version_id=str(calendar_version) if calendar_version is not None else None,
        started_at=model.started_at,
        paused_at=model.paused_at,
        stopped_at=model.stopped_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _order_response(model: PaperOrderModel) -> PaperOrderResponse:
    return PaperOrderResponse(
        id=model.id,
        client_order_id=model.client_order_id,
        order_intent_id=model.order_intent_id,
        risk_decision_id=model.risk_decision_id,
        instrument_id=model.instrument_id,
        side=model.side,
        requested_quantity=model.requested_quantity,
        accepted_quantity=model.accepted_quantity,
        filled_quantity=model.filled_quantity,
        order_type=model.order_type,
        limit_price=model.limit_price,
        status=model.status,
        submitted_session_date=model.submitted_session_date,
        execution_session_date=model.execution_session_date,
        reject_reason=model.reject_reason,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _fill_response(model: PaperFillModel) -> PaperFillResponse:
    return PaperFillResponse(
        id=model.id,
        paper_order_id=model.paper_order_id,
        instrument_id=model.instrument_id,
        side=model.side,
        quantity=model.quantity,
        raw_price=model.raw_price,
        slippage=model.slippage,
        fill_price=model.fill_price,
        commission=model.commission,
        stamp_tax=model.stamp_tax,
        transfer_fee=model.transfer_fee,
        total_fee=model.total_fee,
        trade_date=model.trade_date,
        created_at=model.created_at,
    )


def _instrument_meta(request: Request, instrument_id: str) -> tuple[str | None, str | None]:
    with Session(request.app.state.sqlite_engine) as session:
        model = session.get(InstrumentModel, instrument_id)
    if model is None:
        return None, None
    return model.instrument_type, model.symbol


def _position_response(request: Request, model: PaperPositionModel) -> PaperPositionResponse:
    security_type, symbol = _instrument_meta(request, model.instrument_id)
    return PaperPositionResponse(
        instrument_id=model.instrument_id,
        security_type=security_type,
        symbol=symbol,
        total_quantity=model.total_quantity,
        sellable_quantity=model.sellable_quantity,
        average_cost=model.average_cost,
        market_value=model.market_value,
        unrealized_pnl=model.unrealized_pnl,
        realized_pnl=model.realized_pnl,
        updated_at=model.updated_at,
    )


def _equity_response(model: PaperAccountSnapshotModel) -> EquityPointResponse:
    return EquityPointResponse(
        session_date=model.session_date,
        cash=model.cash,
        market_value=model.market_value,
        equity=model.equity,
        gross_exposure=model.gross_exposure,
        daily_pnl=model.daily_pnl,
        cumulative_pnl=model.cumulative_pnl,
        drawdown=model.drawdown,
    )


def _audit_response(model: PaperAuditEventModel) -> AuditEventResponse:
    return AuditEventResponse(
        id=model.id,
        event_type=model.event_type,
        payload=cast(dict[str, object], json.loads(model.payload_json)),
        created_at=model.created_at,
    )


def _policy_response(
    policy: PaperRiskPolicyModel, version: PaperRiskPolicyVersionModel
) -> RiskPolicyResponse:
    return RiskPolicyResponse(
        policy_id=policy.id,
        name=policy.name,
        status=policy.status,
        version_id=version.id,
        version=version.version,
        fingerprint=version.policy_fingerprint,
        max_single_order_notional=version.max_single_order_notional,
        max_single_position_weight=version.max_single_position_weight,
        max_total_exposure=version.max_total_exposure,
        cash_buffer_ratio=version.cash_buffer_ratio,
        max_daily_loss=version.max_daily_loss,
        max_drawdown=version.max_drawdown,
        max_open_orders=version.max_open_orders,
        allowed_security_types=json.loads(version.allowed_security_types_json),
    )


def _decision_response(
    request: Request, model: PaperRiskDecisionModel
) -> RiskDecisionResponse:
    with Session(request.app.state.sqlite_engine) as session:
        version = session.get(PaperRiskPolicyVersionModel, model.risk_policy_version_id)
    fingerprint = version.policy_fingerprint if version is not None else ""
    return RiskDecisionResponse(
        id=model.id,
        order_intent_id=model.order_intent_id,
        decision=model.decision,
        reason_codes=cast(list[str], json.loads(model.reason_codes_json)),
        risk_policy_version=model.risk_policy_version,
        risk_policy_fingerprint=fingerprint,
        evaluated_metrics=_decision_metrics(model),
        evaluated_at=model.evaluated_at,
    )


def _decision_metrics(model: PaperRiskDecisionModel) -> dict[str, object]:
    market_context = cast(dict[str, object], json.loads(model.market_context_json))
    return cast(dict[str, object], market_context.get("evaluated_metrics") or {})


def _manual_intent_response(
    request: Request, model: PaperOrderIntentModel
) -> ManualIntentResponse:
    with Session(request.app.state.sqlite_engine) as session:
        decision = session.scalar(
            select(PaperRiskDecisionModel).where(
                PaperRiskDecisionModel.order_intent_id == model.id
            )
        )
    risk_status = decision.decision if decision is not None else "PENDING"
    return ManualIntentResponse(
        id=model.id,
        paper_session_id=model.paper_session_id,
        source_type=model.source_type,
        instrument_id=model.instrument_id,
        side=model.side,
        quantity=model.quantity,
        order_type=model.order_type,
        limit_price=model.limit_price,
        signal_session_date=model.signal_session_date,
        intended_execution_session=model.intended_execution_session,
        idempotency_key=model.idempotency_key,
        risk_status=risk_status,
        created_at=model.created_at,
    )


# --- accounts ---


@router.post("/accounts", response_model=PaperAccountResponse, status_code=201)
def create_account(request: Request, payload: PaperAccountCreate):
    try:
        model = _repository(request).create_account(
            name=payload.name,
            initial_cash=payload.initial_cash,
            base_currency=payload.base_currency,
        )
        return _account_response(model)
    except PaperError as error:
        return _error(error)


@router.get("/accounts", response_model=PaperAccountList)
def list_accounts(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return PaperAccountList(
            items=tuple(
                _account_response(item)
                for item in _repository(request).list_accounts()
            )[offset : offset + limit]
        )
    except PaperError as error:
        return _error(error)


@router.get("/accounts/{account_id}", response_model=PaperAccountResponse)
def get_account(request: Request, account_id: str):
    try:
        return _account_response(_repository(request).get_account(account_id))
    except PaperError as error:
        return _error(error)


# --- sessions ---


@router.post("/sessions", response_model=PaperSessionResponse, status_code=201)
def create_session(request: Request, payload: PaperSessionCreate):
    try:
        execution_config = {
            "fee_policy": payload.execution_config.fee_policy,
            "slippage_policy": payload.execution_config.slippage_policy,
            "max_volume_participation": (
                str(payload.execution_config.max_volume_participation)
                if payload.execution_config.max_volume_participation is not None
                else None
            ),
        }
        view = _session_service(request).create_session(
            name=payload.name,
            paper_account_id=payload.paper_account_id,
            market_data_profile_id=payload.market_data_profile_id,
            strategy_version_id=payload.strategy_version_id,
            replay_start_date=payload.replay_start_date,
            replay_end_date=payload.replay_end_date,
            execution_config=execution_config,
        )
        model = _repository(request).get_session(view.paper_session_id)
        return _session_response(model)
    except (PaperError, DatasetError) as error:
        return _error(error)


@router.get("/sessions", response_model=PaperSessionList)
def list_sessions(
    request: Request,
    account_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return PaperSessionList(
            items=tuple(
                _session_response(item)
                for item in _repository(request).list_sessions(
                    paper_account_id=account_id, status=status, limit=limit, offset=offset
                )
            )
        )
    except PaperError as error:
        return _error(error)


@router.get("/sessions/{session_id}", response_model=PaperSessionResponse)
def get_session(request: Request, session_id: str):
    try:
        return _session_response(_repository(request).get_session(session_id))
    except PaperError as error:
        return _error(error)


# --- lifecycle ---


@router.post("/sessions/{session_id}/start", response_model=PaperSessionResponse)
def start_session(request: Request, session_id: str, payload: LifecycleRequest):
    try:
        _session_service(request).start_session(
            session_id, expected_version=payload.expected_version
        )
        return _session_response(_repository(request).get_session(session_id))
    except PaperError as error:
        return _error(error)


@router.post("/sessions/{session_id}/pause", response_model=PaperSessionResponse)
def pause_session(request: Request, session_id: str, payload: LifecycleRequest):
    try:
        _session_service(request).pause_session(
            session_id, expected_version=payload.expected_version
        )
        return _session_response(_repository(request).get_session(session_id))
    except PaperError as error:
        return _error(error)


@router.post("/sessions/{session_id}/resume", response_model=PaperSessionResponse)
def resume_session(request: Request, session_id: str, payload: LifecycleRequest):
    try:
        _session_service(request).resume_session(
            session_id, expected_version=payload.expected_version
        )
        return _session_response(_repository(request).get_session(session_id))
    except PaperError as error:
        return _error(error)


@router.post("/sessions/{session_id}/stop", response_model=PaperSessionResponse)
def stop_session(request: Request, session_id: str, payload: LifecycleRequest):
    try:
        _session_service(request).stop_session(
            session_id, expected_version=payload.expected_version
        )
        return _session_response(_repository(request).get_session(session_id))
    except PaperError as error:
        return _error(error)


# --- advance ---


@router.post("/sessions/{session_id}/advance", response_model=PaperAdvanceResponse)
def advance_session(request: Request, session_id: str, payload: AdvanceRequest):
    try:
        result = _session_service(request).advance_session(
            AdvanceSessionRequest(
                paper_session_id=session_id,
                idempotency_key=payload.idempotency_key,
                expected_version=payload.expected_version,
                expected_current_session_date=payload.expected_current_session_date,
            )
        )
        return PaperAdvanceResponse(
            paper_session_id=result.paper_session_id,
            previous_session_date=result.previous_session_date,
            resulting_session_date=result.resulting_session_date,
            session_version=result.session_version,
            executed_order_count=len(result.executed_orders),
            fill_count=len(result.fills),
            risk_approved_count=result.risk_approved_count,
            risk_rejected_count=result.risk_rejected_count,
            created_order_ids=result.created_order_ids,
            cash=result.cash,
            market_value=result.market_value,
            account_equity=result.account_equity,
            snapshot_id=result.snapshot_id,
            idempotent_replay=result.idempotent_replay,
            no_future_session=result.no_future_session,
        )
    except (PaperError, DatasetError) as error:
        return _error(error)


# --- manual intent ---


@router.post(
    "/sessions/{session_id}/order-intents",
    response_model=ManualIntentResponse,
    status_code=201,
)
def create_manual_intent(request: Request, session_id: str, payload: ManualIntentCreate):
    try:
        model = _session_service(request).create_manual_intent(
            paper_session_id=session_id,
            idempotency_key=payload.idempotency_key,
            instrument_id=payload.instrument_id,
            side=payload.side,
            quantity=payload.quantity,
            order_type=payload.order_type,
            limit_price=payload.limit_price,
            reason=payload.reason,
            metadata=payload.metadata,
        )
        return _manual_intent_response(request, model)
    except PaperError as error:
        return _error(error)


# --- orders / cancel ---


@router.get("/sessions/{session_id}/orders", response_model=PaperOrderList)
def list_orders(
    request: Request,
    session_id: str,
    status: str | None = None,
    instrument_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return PaperOrderList(
            items=tuple(
                _order_response(item)
                for item in _repository(request).list_orders(
                    session_id,
                    status=status,
                    instrument_id=instrument_id,
                    limit=limit,
                    offset=offset,
                )
            )
        )
    except PaperError as error:
        return _error(error)


@router.post("/orders/{order_id}/cancel", response_model=PaperOrderResponse)
def cancel_order(request: Request, order_id: str, payload: CancelOrderRequest):
    try:
        model = _session_service(request).cancel_order(
            order_id, expected_status=payload.expected_status
        )
        return _order_response(model)
    except PaperError as error:
        return _error(error)


# --- fills ---


@router.get("/sessions/{session_id}/fills", response_model=PaperFillList)
def list_fills(
    request: Request,
    session_id: str,
    instrument_id: str | None = None,
    trade_date: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        from datetime import date as _date

        parsed_date = _date.fromisoformat(trade_date) if trade_date else None
        return PaperFillList(
            items=tuple(
                _fill_response(item)
                for item in _repository(request).list_fills(
                    session_id,
                    instrument_id=instrument_id,
                    trade_date=parsed_date,
                    limit=limit,
                    offset=offset,
                )
            )
        )
    except (PaperError, ValueError) as error:
        if isinstance(error, ValueError):
            return JSONResponse(
                status_code=400, content={"error_code": "INVALID_DATE", "message": "日期格式无效"}
            )
        return _error(error)


# --- positions ---


@router.get("/sessions/{session_id}/positions", response_model=PaperPositionList)
def list_positions(
    request: Request,
    session_id: str,
    include_closed: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        paper_session = _repository(request).get_session(session_id)
        return PaperPositionList(
            items=tuple(
                _position_response(request, item)
                for item in _repository(request).list_positions(
                    paper_session.paper_account_id,
                    include_closed=include_closed,
                    limit=limit,
                    offset=offset,
                )
            )
        )
    except PaperError as error:
        return _error(error)


# --- equity ---


@router.get("/sessions/{session_id}/equity", response_model=EquitySeries)
def list_equity(
    request: Request,
    session_id: str,
    start: str | None = None,
    end: str | None = None,
):
    try:
        from datetime import date as _date

        parsed_start = _date.fromisoformat(start) if start else None
        parsed_end = _date.fromisoformat(end) if end else None
        return EquitySeries(
            items=tuple(
                _equity_response(item)
                for item in _repository(request).list_snapshots(
                    session_id, start=parsed_start, end=parsed_end, limit=5000
                )
            )
        )
    except (PaperError, ValueError) as error:
        if isinstance(error, ValueError):
            return JSONResponse(
                status_code=400, content={"error_code": "INVALID_DATE", "message": "日期格式无效"}
            )
        return _error(error)


# --- audit ---


@router.get("/sessions/{session_id}/audit", response_model=AuditEventList)
def list_audit(
    request: Request,
    session_id: str,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return AuditEventList(
            items=tuple(
                _audit_response(item)
                for item in _repository(request).list_audit(
                    session_id, event_type=event_type, limit=limit, offset=offset
                )
            )
        )
    except PaperError as error:
        return _error(error)


# --- risk decisions ---


@router.get("/sessions/{session_id}/risk-decisions", response_model=RiskDecisionList)
def list_risk_decisions(
    request: Request,
    session_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    try:
        return RiskDecisionList(
            items=tuple(
                _decision_response(request, item)
                for item in _repository(request).list_risk_decisions(
                    session_id, limit=limit, offset=offset
                )
            )
        )
    except PaperError as error:
        return _error(error)


# --- risk policy ---


@router.get("/accounts/{account_id}/risk", response_model=RiskPolicyResponse)
def get_risk_policy(request: Request, account_id: str):
    try:
        policy = _policy_service(request).get_active_policy(paper_account_id=account_id)
        if policy is None:
            raise PaperError("RISK_POLICY_NOT_FOUND", "账户无ACTIVE风控策略")
        version = _policy_service(request).get_latest_version(risk_policy_id=policy.id)
        return _policy_response(policy, version)
    except PaperError as error:
        return _error(error)


@router.post("/accounts/{account_id}/risk", response_model=RiskPolicyResponse, status_code=201)
def create_risk_policy(request: Request, account_id: str, payload: RiskPolicyCreate):
    try:
        version = _policy_service(request).create_policy_with_version(
            paper_account_id=account_id,
            name=payload.name,
            max_single_order_notional=payload.max_single_order_notional,
            max_single_position_weight=payload.max_single_position_weight,
            max_total_exposure=payload.max_total_exposure,
            cash_buffer_ratio=payload.cash_buffer_ratio,
            max_daily_loss=payload.max_daily_loss,
            max_drawdown=payload.max_drawdown,
            max_open_orders=payload.max_open_orders,
            allowed_security_types=payload.allowed_security_types,
        )
        policy = _repository(request).get_risk_policy(version.risk_policy_id)
        return _policy_response(policy, version)
    except PaperError as error:
        return _error(error)


@router.patch("/accounts/{account_id}/risk", response_model=RiskPolicyResponse)
def patch_risk_policy(request: Request, account_id: str, payload: RiskPolicyPatch):
    try:
        policy = _policy_service(request).get_active_policy(paper_account_id=account_id)
        if policy is None:
            raise PaperError("RISK_POLICY_NOT_FOUND", "账户无ACTIVE风控策略")
        kwargs = payload.model_dump(exclude_none=True)
        version = _policy_service(request).patch_version(risk_policy_id=policy.id, **kwargs)
        return _policy_response(policy, version)
    except PaperError as error:
        return _error(error)


# --- freeze / unfreeze ---


@router.post("/accounts/{account_id}/freeze", response_model=PaperAccountResponse)
def freeze_account(request: Request, account_id: str):
    try:
        model = _risk_service(request).freeze_account(account_id=account_id, actor="USER")
        return _account_response(model)
    except PaperError as error:
        return _error(error)


@router.post("/accounts/{account_id}/unfreeze", response_model=PaperAccountResponse)
def unfreeze_account(request: Request, account_id: str):
    try:
        model = _risk_service(request).unfreeze_account(account_id=account_id, actor="USER")
        return _account_response(model)
    except PaperError as error:
        return _error(error)
