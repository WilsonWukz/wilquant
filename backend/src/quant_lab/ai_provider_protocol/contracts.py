"""Versioned, data-only boundary; deliberately independent of Core."""

import hashlib
import json
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AI_PROVIDER_PROTOCOL_VERSION = "1"


def canonical_fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderMessage(Contract):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=100_000)


class ProviderCapabilities(Contract):
    output_token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    reasoning_parameter: Literal["reasoning_effort", "thinking", "unsupported"] = "unsupported"
    reasoning_content_field: str = "reasoning_content"
    supports_json_object: bool = True
    supports_json_schema: bool = False
    input_usage_field: str = "prompt_tokens"
    output_usage_field: str = "completion_tokens"
    total_usage_field: str = "total_tokens"
    reasoning_usage_field: str = "completion_tokens_details.reasoning_tokens"
    cached_usage_field: str = "prompt_tokens_details.cached_tokens"


class EndpointProfile(Contract):
    profile_id: str = Field(min_length=1, max_length=128)
    base_url: str = Field(max_length=2048)
    model: str = Field(min_length=1, max_length=256)
    credential_ref: str = Field(pattern=r"^wilquant\.ai\.[A-Za-z0-9_.-]+$", max_length=256)
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    allow_local_http: bool = False

    @property
    def fingerprint(self) -> str:
        return canonical_fingerprint(self.model_dump(mode="json"))


class CallPolicy(Contract):
    version: Literal["1"] = "1"
    connect_timeout: float = Field(default=5, gt=0, le=300)
    read_timeout: float = Field(default=60, gt=0, le=300)
    write_timeout: float = Field(default=10, gt=0, le=300)
    pool_timeout: float = Field(default=5, gt=0, le=300)
    max_request_bytes: int = Field(default=262144, gt=0)
    max_response_bytes: int = Field(default=1048576, gt=0)
    max_output_tokens: int = Field(default=8192, gt=0)
    max_messages: int = Field(default=128, gt=0, le=128)
    max_chars_per_message: int = Field(default=100000, gt=0, le=100000)
    max_reasoning_bytes: int = Field(default=131072, gt=0)
    max_raw_artifact_bytes: int = Field(default=262144, gt=0)
    replay_cache_size: int = Field(default=10000, gt=0)
    timestamp_skew_seconds: int = Field(default=30, gt=0, le=30)


class ProviderCallRequest(Contract):
    protocol_version: Literal["1"] = "1"
    request_id: str = Field(min_length=1, max_length=128)
    timestamp_utc: datetime
    profile_id: str = Field(min_length=1, max_length=128)
    endpoint_fingerprint: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    messages: list[ProviderMessage] = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int = Field(gt=0, le=1_000_000)
    reasoning_enabled: bool = False
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    response_format: Literal["TEXT", "JSON_OBJECT", "JSON_SCHEMA"] = "TEXT"
    credential_ref: str = Field(pattern=r"^wilquant\.ai\.[A-Za-z0-9_.-]+$", max_length=256)

    @field_validator("timestamp_utc")
    @classmethod
    def utc_only(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("UTC timestamp required")
        return value


class ProviderUsage(Contract):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cached_prompt_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if (
            self.prompt_tokens is not None
            and self.cached_prompt_tokens is not None
            and self.cached_prompt_tokens > self.prompt_tokens
        ):
            raise ValueError("Inconsistent usage")
        if (
            self.prompt_tokens is not None
            and self.completion_tokens is not None
            and self.total_tokens is not None
            and self.total_tokens != self.prompt_tokens + self.completion_tokens
        ):
            raise ValueError("Inconsistent usage")
        return self


class ProviderCallResult(Contract):
    protocol_version: Literal["1"] = "1"
    request_id: str
    endpoint_fingerprint: str
    model_requested: str
    model_reported: str | None = None
    content: str
    reasoning_content: str | None = None
    raw_response: str | None = None
    usage: ProviderUsage = Field(default_factory=ProviderUsage)
    finish_reason: str | None = None
    latency_ms: float = Field(default=0, ge=0)
    provider_response_id: str | None = None


class ProviderCallError(Contract):
    code: str
    safe_message: str = "Provider call failed"
    outcome_unknown: bool = False


class ProviderHealth(Contract):
    protocol_version: Literal["1"] = "1"
    status: Literal["ready", "unavailable"] = "ready"
    profile_id: str
    endpoint_fingerprint: str


class ProviderAvailability(Contract):
    """Local readiness only; makes no claim about upstream authentication or health."""

    protocol_version: Literal["1"] = "1"
    profile_id: str = Field(min_length=1, max_length=128)
    endpoint_fingerprint: str = Field(min_length=1, max_length=128)
    host_ready: bool = Field(strict=True)
    profile_valid: bool = Field(strict=True)
    credential_store_accessible: bool = Field(strict=True)
    credential_available: bool = Field(strict=True)


class ProviderFailure(Exception):
    def __init__(
        self, code: str, safe_message: str = "Provider call failed", outcome_unknown: bool = False
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.outcome_unknown = outcome_unknown
        super().__init__(safe_message)

    def as_error(self) -> ProviderCallError:
        return ProviderCallError(
            code=self.code, safe_message=self.safe_message, outcome_unknown=self.outcome_unknown
        )
