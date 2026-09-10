from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError


def test_protocol_rejects_unbounded_options_and_preserves_unknown_usage():
    from quant_lab.ai_provider_protocol import ProviderCallRequest, ProviderUsage

    assert ProviderUsage().prompt_tokens is None
    with pytest.raises(ValidationError):
        ProviderCallRequest(
            request_id="r",
            timestamp_utc=datetime.now(UTC),
            profile_id="p",
            endpoint_fingerprint="f",
            model="m",
            messages=[{"role": "user", "content": "hi"}],
            max_output_tokens=10,
            credential_ref="wilquant.ai.test",
            tools=[],
        )


def profile_and_request():
    from quant_lab.ai_provider_protocol import EndpointProfile, ProviderCallRequest

    profile = EndpointProfile(
        profile_id="p",
        base_url="https://example.com/v1",
        model="m",
        credential_ref="wilquant.ai.test",
    )
    request = ProviderCallRequest(
        request_id="r",
        timestamp_utc=datetime.now(UTC),
        profile_id="p",
        endpoint_fingerprint=profile.fingerprint,
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        max_output_tokens=10,
        credential_ref="wilquant.ai.test",
    )
    return profile, request


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("timeout", "PROVIDER_TIMEOUT"),
        ("429", "PROVIDER_RATE_LIMITED"),
        ("500", "PROVIDER_UNAVAILABLE"),
        ("malformed", "PROVIDER_INVALID_RESPONSE"),
    ],
)
def test_fake_failures(scenario, code):
    from quant_lab.ai_provider_host import FakeProvider
    from quant_lab.ai_provider_protocol import ProviderFailure

    profile, request = profile_and_request()
    with pytest.raises(ProviderFailure) as failure:
        FakeProvider(profile, scenario=scenario).complete(request)
    assert failure.value.code == code
    assert failure.value.outcome_unknown == (scenario == "timeout")


def test_fake_configurable_success():
    from quant_lab.ai_provider_host import FakeProvider
    from quant_lab.ai_provider_protocol import ProviderUsage

    profile, request = profile_and_request()
    result = FakeProvider(
        profile,
        content="candidate",
        reasoning_content="private",
        usage=ProviderUsage(prompt_tokens=1),
        finish_reason="length",
        latency_ms=12,
    ).complete(request)
    assert result.content == "candidate"
    assert result.reasoning_content == "private"
    assert result.usage.prompt_tokens == 1
    assert result.usage.completion_tokens is None
    assert result.finish_reason == "length"
    assert result.latency_ms == 12
    assert result.raw_response is None


def test_host_auth_replay_and_success():
    from fastapi.testclient import TestClient

    from quant_lab.ai_provider_host import FakeProvider, create_app

    profile, request = profile_and_request()
    provider = FakeProvider(profile)
    with TestClient(create_app(profile, provider, "x" * 64)) as client:
        assert client.get("/internal/v1/health").status_code == 401
        headers = {"Authorization": "Bearer " + "x" * 64, "X-AI-Protocol-Version": "1"}
        response = client.post(
            "/internal/v1/complete", headers=headers, json=request.model_dump(mode="json")
        )
        assert response.status_code == 200
        assert response.json()["content"] == '{"status":"ok"}'
        assert (
            client.post(
                "/internal/v1/complete", headers=headers, json=request.model_dump(mode="json")
            ).status_code
            == 409
        )
        assert provider.invocation_count == 1


@pytest.mark.parametrize(
    "change,code",
    [
        (
            {"timestamp_delta": -60},
            "REQUEST_TIMESTAMP_INVALID",
        ),
        (
            {"timestamp_delta": 60},
            "REQUEST_TIMESTAMP_INVALID",
        ),
        ({"tools": []}, "PROVIDER_TOOLS_NOT_ALLOWED"),
        ({"model": "other"}, "PROFILE_MISMATCH"),
    ],
)
def test_host_rejects_before_provider(change, code):
    from fastapi.testclient import TestClient

    from quant_lab.ai_provider_host import FakeProvider, create_app

    if "timestamp_delta" in change:
        change = {
            "timestamp_utc": (
                datetime.now(UTC) + timedelta(seconds=change["timestamp_delta"])
            ).isoformat()
        }
    profile, request = profile_and_request()
    provider = FakeProvider(profile)
    with TestClient(create_app(profile, provider, "x" * 64)) as client:
        response = client.post(
            "/internal/v1/complete",
            headers={"Authorization": "Bearer " + "x" * 64, "X-AI-Protocol-Version": "1"},
            json=request.model_dump(mode="json") | change,
        )
        assert response.json()["error"]["code"] == code
        assert provider.invocation_count == 0


def test_replay_cache_full_fails_closed():
    from quant_lab.ai_provider_host.app import ReplayCache
    from quant_lab.ai_provider_protocol import ProviderFailure

    cache = ReplayCache(1, 30)
    cache.claim("one", datetime.now(UTC) + timedelta(seconds=25))
    with pytest.raises(ProviderFailure) as error:
        cache.claim("two", datetime.now(UTC))
    assert error.value.code == "REPLAY_CACHE_FULL"
    with pytest.raises(ProviderFailure) as error:
        cache.claim("one", datetime.now(UTC))
    assert error.value.code == "DUPLICATE_PROVIDER_REQUEST"


def test_profile_fingerprint_includes_capabilities():
    from quant_lab.ai_provider_protocol import EndpointProfile, ProviderCapabilities

    profile = EndpointProfile(
        profile_id="p",
        base_url="https://example.com/v1",
        model="m",
        credential_ref="wilquant.ai.test",
    )
    assert (
        profile.fingerprint
        != profile.model_copy(
            update={
                "capabilities": ProviderCapabilities(
                    output_token_parameter="max_completion_tokens"
                ),
            }
        ).fingerprint
    )
