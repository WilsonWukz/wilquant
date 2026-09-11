"""Bounded protocol adapters; no Core imports."""

from typing import Protocol

from quant_lab.ai_provider_protocol import (
    EndpointProfile,
    ProviderAvailability,
    ProviderCallRequest,
    ProviderCallResult,
    ProviderCapabilities,
    ProviderFailure,
    ProviderHealth,
    ProviderUsage,
)


class Provider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def complete(self, request: ProviderCallRequest) -> ProviderCallResult: ...
    def health(self) -> ProviderHealth: ...
    def availability(self) -> ProviderAvailability: ...


class FakeProvider:
    def __init__(
        self,
        profile: EndpointProfile,
        scenario: str = "success",
        *,
        content: str = '{"status":"ok"}',
        reasoning_content: str | None = None,
        usage: ProviderUsage | None = None,
        finish_reason: str | None = "stop",
        latency_ms: float = 0,
    ) -> None:
        if scenario not in {"success", "timeout", "429", "500", "malformed"}:
            raise ValueError("Unknown fake scenario")
        self.profile = profile
        self.scenario = scenario
        self.invocation_count = 0
        self.content = content
        self.reasoning_content = reasoning_content
        self.usage = (
            usage
            if usage is not None
            else ProviderUsage(prompt_tokens=2, completion_tokens=5, total_tokens=7)
        )
        self.finish_reason = finish_reason
        self.latency_ms = latency_ms

    def capabilities(self) -> ProviderCapabilities:
        return self.profile.capabilities

    def health(self) -> ProviderHealth:
        return ProviderHealth(
            profile_id=self.profile.profile_id, endpoint_fingerprint=self.profile.fingerprint
        )

    def availability(self) -> ProviderAvailability:
        # Fake providers explicitly require no credential store or upstream credentials.
        return ProviderAvailability(
            profile_id=self.profile.profile_id,
            endpoint_fingerprint=self.profile.fingerprint,
            host_ready=True,
            profile_valid=True,
            credential_store_accessible=True,
            credential_available=True,
        )

    def complete(self, request: ProviderCallRequest) -> ProviderCallResult:
        self.invocation_count += 1
        errors = {
            "timeout": "PROVIDER_TIMEOUT",
            "429": "PROVIDER_RATE_LIMITED",
            "500": "PROVIDER_UNAVAILABLE",
            "malformed": "PROVIDER_INVALID_RESPONSE",
        }
        if self.scenario in errors:
            raise ProviderFailure(errors[self.scenario], outcome_unknown=self.scenario == "timeout")
        return ProviderCallResult(
            request_id=request.request_id,
            endpoint_fingerprint=self.profile.fingerprint,
            model_requested=request.model,
            model_reported=request.model,
            content=self.content,
            reasoning_content=self.reasoning_content,
            finish_reason=self.finish_reason,
            latency_ms=self.latency_ms,
            provider_response_id="fake-" + request.request_id,
            usage=self.usage,
        )
