"""Typed non-secret AI-3 configuration; Core-only, never imported by the Host."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_lab.ai.provider_budget import ProviderBudgetPolicy
from quant_lab.ai_provider_protocol import CallPolicy, EndpointProfile


class ProviderModelParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider_profile: EndpointProfile
    budget: ProviderBudgetPolicy = Field(default_factory=ProviderBudgetPolicy)
    call_policy: CallPolicy = Field(default_factory=CallPolicy)
    max_output_tokens: int = Field(default=256, ge=1)
    temperature: Decimal | None = Field(default=None, ge=0, le=2)
    reasoning_enabled: bool = False
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    response_format: Literal["TEXT", "JSON_OBJECT"] = "TEXT"


def provider_config_json(value: object) -> object:
    # AI-1 canonical JSON deliberately rejects float. Preserve decimal spelling in
    # persisted configuration; Pydantic projects it explicitly to wire floats later.
    if isinstance(value, float):
        return str(Decimal(str(value)))
    if isinstance(value, dict):
        return {key: provider_config_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [provider_config_json(item) for item in value]
    return value
