from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=100)
    market: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=32)
    symbol: str = Field(min_length=1, max_length=64)
    instrument_id: str = Field(min_length=1, max_length=100)
    asset_type: str = Field(min_length=1, max_length=32)
    currency: str = Field(min_length=1, max_length=8)
    timeframe: str = Field(min_length=1, max_length=32)
    as_of_utc: datetime
    market_local_trade_date: date
    bindings: dict[str, object]
    previous_case_id: str | None = None
    previous_analysis_run_id: str | None = None
    thesis_revision_id: str | None = None


class ResearchCaseResponse(BaseModel):
    id: str
    purpose: str
    market: str
    exchange: str
    symbol: str
    instrument_id: str
    asset_type: str
    currency: str
    timeframe: str
    as_of_utc: datetime
    market_local_trade_date: date
    bindings: dict[str, object]
    previous_case_id: str | None
    previous_analysis_run_id: str | None
    thesis_revision_id: str | None
    fingerprint: str
    created_by: str
    created_at: datetime


class AIAnalysisRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    stage: Literal["DIAGNOSIS", "RECOMMENDATION", "CONVERSATION"]
    prompt_template_version_id: str
    model_config_version_id: str
    resolved_prompt_fingerprint: str = Field(min_length=64, max_length=64)
    validator_policy_version: str = Field(min_length=1, max_length=64)
    validator_policy_fingerprint: str = Field(min_length=64, max_length=64)
    parent_run_id: str | None = None


class AIAnalysisRunResponse(BaseModel):
    id: str
    case_id: str
    stage: str
    status: str
    parent_run_id: str | None
    prompt_template_version_id: str
    model_config_version_id: str
    case_fingerprint: str
    prompt_template_fingerprint: str
    resolved_prompt_fingerprint: str
    model_config_fingerprint: str
    validator_policy_version: str
    validator_policy_fingerprint: str
    input_envelope_fingerprint: str | None
    raw_response_artifact_sha256: str | None
    normalized_output_fingerprint: str | None
    started_at: datetime | None
    completed_at: datetime | None
    failure_code: str | None
    safe_failure_message: str | None
    created_at: datetime


class AITraceEventResponse(BaseModel):
    id: str
    run_id: str
    sequence: int
    event_type: str
    payload: object
    payload_fingerprint: str
    occurred_at: datetime


class AITraceListResponse(BaseModel):
    items: tuple[AITraceEventResponse, ...]


class AIUsageResponse(BaseModel):
    id: str
    run_id: str
    attempt_id: str
    prompt_tokens: int
    cached_prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reported_cost: Decimal | None
    estimated_cost: Decimal | None
    currency: str
    is_estimate: bool
    occurred_at: datetime


class AIUsageListResponse(BaseModel):
    items: tuple[AIUsageResponse, ...]
