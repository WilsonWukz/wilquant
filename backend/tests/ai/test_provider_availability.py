from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from quant_lab.ai_provider_client import AIProviderHostClient
from quant_lab.ai_provider_host import FakeProvider, create_app
from quant_lab.ai_provider_host.openai_compatible import OpenAICompatibleProvider
from quant_lab.ai_provider_host.secrets import WindowsCredentialManagerSecretStore
from quant_lab.ai_provider_protocol import EndpointProfile, ProviderFailure

TOKEN = "a" * 64
PATH = "/internal/v1/availability"


def profile():
    return EndpointProfile(
        profile_id="p",
        base_url="http://127.0.0.1:9999/v1",
        model="m",
        credential_ref="wilquant.ai.test",
        allow_local_http=True,
    )


def headers():
    return {
        "Authorization": "Bearer " + TOKEN,
        "X-AI-Protocol-Version": "1",
        "X-Request-ID": str(uuid4()),
        "X-Timestamp-UTC": datetime.now(UTC).isoformat(),
    }


@pytest.mark.parametrize(
    "state,accessible,available",
    [
        ("missing", True, False),
        ("denied", False, False),
        ("present", True, True),
    ],
)
def test_host_local_availability_never_calls_upstream(monkeypatch, state, accessible, available):
    class Native:
        def read(self, target):
            assert target == "wilquant.ai.test"
            if state == "denied":
                raise RuntimeError("private-store-detail")
            return "test-secret-never-returned" if state == "present" else None

    endpoint = profile()
    provider = OpenAICompatibleProvider(endpoint, WindowsCredentialManagerSecretStore(Native()))

    def forbidden(*args, **kwargs):
        pytest.fail("availability attempted upstream HTTP, DNS, health or completion")

    monkeypatch.setattr(provider, "health", forbidden)
    monkeypatch.setattr(provider, "complete", forbidden)
    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    with TestClient(create_app(endpoint, provider, TOKEN)) as client:
        response = client.get(PATH, headers=headers())
    assert response.status_code == 200
    assert response.json() == {
        "protocol_version": "1",
        "profile_id": "p",
        "endpoint_fingerprint": endpoint.fingerprint,
        "host_ready": True,
        "profile_valid": True,
        "credential_store_accessible": accessible,
        "credential_available": available,
    }
    assert "test-secret" not in response.text
    assert "private-store-detail" not in response.text


def test_fake_availability_needs_no_credentials_and_reuses_security():
    endpoint = profile()
    provider = FakeProvider(endpoint)
    with TestClient(create_app(endpoint, provider, TOKEN)) as client:
        assert client.get(PATH).status_code == 401
        valid = headers()
        response = client.get(PATH, headers=valid)
        assert response.status_code == 200
        assert response.json()["credential_available"] is True
        assert response.json()["credential_store_accessible"] is True
        assert client.get(PATH, headers=valid).json()["error"]["code"] == (
            "DUPLICATE_PROVIDER_REQUEST"
        )
        assert (
            client.get(PATH, headers=headers() | {"X-AI-Protocol-Version": "2"}).json()["error"][
                "code"
            ]
            == "PROTOCOL_VERSION_MISMATCH"
        )
        expired = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        assert (
            client.get(PATH, headers=headers() | {"X-Timestamp-UTC": expired}).json()["error"][
                "code"
            ]
            == "REQUEST_TIMESTAMP_INVALID"
        )
    assert provider.invocation_count == 0


@pytest.mark.parametrize("invalid", [False, True])
def test_client_availability_uses_authenticated_get_and_validates_response(
    tmp_path,
    monkeypatch,
    invalid,
):
    endpoint = profile()
    token_path = tmp_path / "host-token"
    token_path.write_text(TOKEN)
    observed = []

    def respond(request):
        observed.append(request)
        assert request.method == "GET"
        assert request.url.path == PATH
        assert request.headers["authorization"] == "Bearer " + TOKEN
        assert request.headers["x-ai-protocol-version"] == "1"
        assert request.headers["x-request-id"]
        assert request.headers["x-timestamp-utc"]
        assert not request.content
        return httpx.Response(
            200,
            json={
                "protocol_version": "1",
                "profile_id": "p",
                "endpoint_fingerprint": endpoint.fingerprint,
                "host_ready": "true" if invalid else True,
                "profile_valid": True,
                "credential_store_accessible": True,
                "credential_available": False,
            },
        )

    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(respond))
    client = AIProviderHostClient("http://127.0.0.1:8011", token_path)
    if invalid:
        with pytest.raises(ProviderFailure) as error:
            client.availability()
        assert error.value.code == "PROVIDER_INVALID_RESPONSE"
        assert error.value.outcome_unknown is False
    else:
        result = client.availability()
        assert result.host_ready is True
        assert result.credential_available is False
        assert result.endpoint_fingerprint == endpoint.fingerprint
    assert len(observed) == 1


@pytest.mark.parametrize(
    "status,payload",
    [
        (200, {"host_ready": True}),
        (200, {"provider_authenticated": True}),
        (200, []),
        (400, {"error": {"unsafe": "test-secret-never-returned"}}),
        (400, []),
    ],
)
def test_client_rejects_malformed_availability_and_error_schemas(
    tmp_path,
    monkeypatch,
    status,
    payload,
):
    token_path = tmp_path / "host-token"
    token_path.write_text(TOKEN)
    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda **kwargs: httpx.MockTransport(lambda request: httpx.Response(status, json=payload)),
    )
    with pytest.raises(ProviderFailure) as error:
        AIProviderHostClient("http://127.0.0.1:8011", token_path).availability()
    assert error.value.code == "PROVIDER_INVALID_RESPONSE"
    assert error.value.outcome_unknown is False
    assert "test-secret" not in str(error.value)
