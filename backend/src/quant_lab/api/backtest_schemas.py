from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BacktestCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    market_data_profile_id: str
    strategy_type: str
    strategy_version_id: str | None = None
    strategy_spec: dict[str, object] | None = None
    start_date: date
    end_date: date
    initial_cash: Decimal = Field(gt=0)
    fee_policy: dict[str, object] = Field(default_factory=dict)
    slippage_policy: dict[str, object] = Field(default_factory=dict)
    max_volume_participation: Decimal | None = Field(default=None, gt=0, le=1)
    instrument_metadata_overrides: dict[str, object] = Field(default_factory=dict)


class BacktestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    backtest_run_id: str
    name: str
    status: str
    market_data_profile_id: str
    market_data_snapshot_fingerprint: str
    strategy_type: str
    strategy_version_id: str | None = None
    strategy_fingerprint: str
    config_fingerprint: str
    run_input_fingerprint: str
    initial_cash: Decimal
    start_date: date
    end_date: date
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    artifact_manifest_path: str | None = None


class BacktestListResponse(BaseModel):
    items: tuple[BacktestResponse, ...]
