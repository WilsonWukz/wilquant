from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# --- requests ---


class PaperAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    initial_cash: Decimal = Field(gt=0)
    base_currency: str = "CNY"


class ExecutionConfig(BaseModel):
    fee_policy: dict[str, object] = Field(default_factory=dict)
    slippage_policy: dict[str, object] = Field(default_factory=dict)
    max_volume_participation: Decimal | None = Field(default=None, gt=0, le=1)


class PaperSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    paper_account_id: str
    market_data_profile_id: str
    strategy_version_id: str | None = None
    replay_start_date: date
    replay_end_date: date | None = None
    execution_config: ExecutionConfig = Field(default_factory=ExecutionConfig)


class LifecycleRequest(BaseModel):
    expected_version: int = Field(ge=1)


class AdvanceRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1)
    expected_current_session_date: date | None = None


class ManualIntentCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=64)
    instrument_id: str = Field(min_length=1, max_length=32)
    side: Literal["BUY", "SELL"]
    quantity: int = Field(gt=0)
    order_type: str
    limit_price: Decimal | None = None
    reason: str | None = Field(default=None, max_length=64)
    metadata: dict[str, object] = Field(default_factory=dict)


class CancelOrderRequest(BaseModel):
    expected_status: str | None = None


class RiskPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    max_single_order_notional: Decimal = Field(gt=0)
    max_single_position_weight: Decimal = Field(gt=0, le=1)
    max_total_exposure: Decimal = Field(gt=0, le=1)
    cash_buffer_ratio: Decimal = Field(ge=0, lt=1)
    max_daily_loss: Decimal = Field(ge=0, le=1)
    max_drawdown: Decimal = Field(ge=0, le=1)
    max_open_orders: int = Field(gt=0)
    allowed_security_types: list[str]


class RiskPolicyPatch(BaseModel):
    max_single_order_notional: Decimal | None = Field(default=None, gt=0)
    max_single_position_weight: Decimal | None = Field(default=None, gt=0, le=1)
    max_total_exposure: Decimal | None = Field(default=None, gt=0, le=1)
    cash_buffer_ratio: Decimal | None = Field(default=None, ge=0, lt=1)
    max_daily_loss: Decimal | None = Field(default=None, ge=0, le=1)
    max_drawdown: Decimal | None = Field(default=None, ge=0, le=1)
    max_open_orders: int | None = Field(default=None, gt=0)
    allowed_security_types: list[str] | None = None


# --- responses ---


class PaperAccountResponse(BaseModel):
    id: str
    name: str
    status: str
    base_currency: str
    initial_cash: Decimal
    cash: Decimal
    market_value: Decimal
    account_equity: Decimal
    created_at: datetime
    updated_at: datetime


class PaperSessionResponse(BaseModel):
    id: str
    name: str
    paper_account_id: str
    market_data_profile_id: str
    market_data_snapshot_fingerprint: str
    strategy_version_id: str | None
    status: str
    replay_start_date: date
    replay_end_date: date | None
    current_session_date: date | None
    version: int
    execution_config: dict[str, object]
    execution_config_fingerprint: str
    dataset_version_id: str | None = None
    calendar_version_id: str | None = None
    started_at: datetime | None
    paused_at: datetime | None
    stopped_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaperAdvanceResponse(BaseModel):
    paper_session_id: str
    previous_session_date: date | None
    resulting_session_date: date | None
    session_version: int
    executed_order_count: int
    fill_count: int
    risk_approved_count: int
    risk_rejected_count: int
    created_order_ids: tuple[str, ...]
    cash: Decimal
    market_value: Decimal
    account_equity: Decimal
    snapshot_id: str | None
    idempotent_replay: bool
    no_future_session: bool


class ManualIntentResponse(BaseModel):
    id: str
    paper_session_id: str
    source_type: str
    instrument_id: str
    side: str
    quantity: int
    order_type: str
    limit_price: Decimal | None
    signal_session_date: date
    intended_execution_session: date
    idempotency_key: str
    risk_status: str
    created_at: datetime


class PaperOrderResponse(BaseModel):
    id: str
    client_order_id: str
    order_intent_id: str
    risk_decision_id: str
    instrument_id: str
    side: str
    requested_quantity: int
    accepted_quantity: int
    filled_quantity: int
    order_type: str
    limit_price: Decimal | None
    status: str
    submitted_session_date: date | None
    execution_session_date: date | None
    reject_reason: str | None
    created_at: datetime
    updated_at: datetime


class PaperFillResponse(BaseModel):
    id: str
    paper_order_id: str
    instrument_id: str
    side: str
    quantity: int
    raw_price: Decimal
    slippage: Decimal
    fill_price: Decimal
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    total_fee: Decimal
    trade_date: date
    created_at: datetime


class PaperPositionResponse(BaseModel):
    instrument_id: str
    security_type: str | None = None
    symbol: str | None = None
    total_quantity: int
    sellable_quantity: int
    average_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    updated_at: datetime


class EquityPointResponse(BaseModel):
    session_date: date
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    gross_exposure: Decimal
    daily_pnl: Decimal
    cumulative_pnl: Decimal
    drawdown: Decimal


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime


class RiskPolicyResponse(BaseModel):
    policy_id: str
    name: str
    status: str
    version_id: str
    version: int
    fingerprint: str
    max_single_order_notional: Decimal
    max_single_position_weight: Decimal
    max_total_exposure: Decimal
    cash_buffer_ratio: Decimal
    max_daily_loss: Decimal
    max_drawdown: Decimal
    max_open_orders: int
    allowed_security_types: list[str]


class RiskDecisionResponse(BaseModel):
    id: str
    order_intent_id: str
    decision: str
    reason_codes: list[str]
    risk_policy_version: int
    risk_policy_fingerprint: str
    evaluated_metrics: dict[str, object]
    evaluated_at: datetime


# --- list wrappers ---


class PaperAccountList(BaseModel):
    items: tuple[PaperAccountResponse, ...]


class PaperSessionList(BaseModel):
    items: tuple[PaperSessionResponse, ...]


class PaperOrderList(BaseModel):
    items: tuple[PaperOrderResponse, ...]


class PaperFillList(BaseModel):
    items: tuple[PaperFillResponse, ...]


class PaperPositionList(BaseModel):
    items: tuple[PaperPositionResponse, ...]


class EquitySeries(BaseModel):
    items: tuple[EquityPointResponse, ...]


class AuditEventList(BaseModel):
    items: tuple[AuditEventResponse, ...]


class RiskDecisionList(BaseModel):
    items: tuple[RiskDecisionResponse, ...]
