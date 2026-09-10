import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .test_provider_host import profile_and_request


def test_socket_adapter_maps_capabilities_usage_and_redacts():
    from quant_lab.ai_provider_host import OpenAICompatibleProvider
    from quant_lab.ai_provider_host.secrets import MemorySecretStore
    from quant_lab.ai_provider_protocol import ProviderCapabilities

    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = json.dumps(
                {
                    "id": "reply",
                    "model": "reported",
                    "choices": [
                        {
                            "message": {"content": "secret-key", "reasoning_content": "secret-key"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 3},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    profile, request = profile_and_request()
    profile = profile.model_copy(
        update={
            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "allow_local_http": True,
            "capabilities": ProviderCapabilities(
                output_token_parameter="max_completion_tokens",
                reasoning_parameter="reasoning_effort",
            ),
        }
    )
    request = request.model_copy(
        update={
            "endpoint_fingerprint": profile.fingerprint,
            "reasoning_enabled": True,
            "reasoning_effort": "high",
        }
    )
    store = MemorySecretStore()
    store.set(profile.credential_ref, "secret-key")
    try:
        result = OpenAICompatibleProvider(profile, store).complete(request)
        assert result.content == "[REDACTED]"
        assert result.reasoning_content == "[REDACTED]"
        assert result.raw_response is not None
        assert "secret-key" not in result.raw_response
        assert "reasoning_content" not in result.raw_response
        assert json.loads(result.raw_response)["choices"][0]["message"]["content"] == "[REDACTED]"
        assert result.usage.prompt_tokens == 3
        assert result.usage.completion_tokens is None
        assert captured[0]["max_completion_tokens"] == 10
        assert captured[0]["reasoning_effort"] == "high"
        assert "max_tokens" not in captured[0]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://user@example.com",
        "https://example.com?q=1",
        "https://example.com#x",
    ],
)
def test_unsafe_endpoints_rejected(url):
    from quant_lab.ai_provider_host import OpenAICompatibleProvider
    from quant_lab.ai_provider_host.secrets import MemorySecretStore
    from quant_lab.ai_provider_protocol import ProviderFailure

    profile, _ = profile_and_request()
    with pytest.raises(ProviderFailure):
        OpenAICompatibleProvider(profile.model_copy(update={"base_url": url}), MemorySecretStore())


@pytest.mark.parametrize(
    "status,payload,code",
    [
        (401, {}, "PROVIDER_AUTH_FAILED"),
        (429, {}, "PROVIDER_RATE_LIMITED"),
        (500, {}, "PROVIDER_UNAVAILABLE"),
        (302, {}, "PROVIDER_REJECTED"),
        (400, {"error": "context_length_exceeded"}, "PROVIDER_CONTEXT_LENGTH"),
        (429, {"error": "insufficient_quota"}, "PROVIDER_QUOTA_EXCEEDED"),
        (200, "not-json", "PROVIDER_INVALID_RESPONSE"),
        (200, {}, "PROVIDER_INVALID_RESPONSE"),
        (200, {"choices": [{"message": {}}]}, "PROVIDER_INVALID_RESPONSE"),
    ],
)
def test_socket_errors_never_retry(status, payload, code):
    from quant_lab.ai_provider_host import OpenAICompatibleProvider
    from quant_lab.ai_provider_host.secrets import MemorySecretStore
    from quant_lab.ai_provider_protocol import ProviderFailure

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(1)
            self.rfile.read(int(self.headers["Content-Length"]))
            data = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile, request = profile_and_request()
        profile = profile.model_copy(
            update={
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "allow_local_http": True,
            }
        )
        request = request.model_copy(update={"endpoint_fingerprint": profile.fingerprint})
        store = MemorySecretStore()
        store.set(profile.credential_ref, "secret")
        try:
            with pytest.raises(ProviderFailure) as failure:
                OpenAICompatibleProvider(profile, store).complete(request)
            assert failure.value.code == code
            assert not failure.value.outcome_unknown
            assert calls == [1]
        finally:
            server.shutdown()
            thread.join()


@pytest.mark.parametrize("slow", [True, False])
def test_socket_timeout_and_size_limit(slow):
    from quant_lab.ai_provider_host import OpenAICompatibleProvider
    from quant_lab.ai_provider_host.secrets import MemorySecretStore
    from quant_lab.ai_provider_protocol import CallPolicy, ProviderFailure

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if slow:
                time.sleep(0.2)
                return
            self.send_response(200)
            self.send_header("Content-Length", "9000")
            self.end_headers()
            self.wfile.write(b"x" * 9000)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile, request = profile_and_request()
        profile = profile.model_copy(
            update={
                "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                "allow_local_http": True,
            }
        )
        request = request.model_copy(update={"endpoint_fingerprint": profile.fingerprint})
        store = MemorySecretStore()
        store.set(profile.credential_ref, "secret")
        try:
            with pytest.raises(ProviderFailure) as failure:
                OpenAICompatibleProvider(
                    profile, store, CallPolicy(read_timeout=0.05, max_response_bytes=100)
                ).complete(request)
            assert failure.value.code == (
                "PROVIDER_TIMEOUT" if slow else "PROVIDER_RESPONSE_TOO_LARGE"
            )
            assert failure.value.outcome_unknown == slow
        finally:
            server.shutdown()
            thread.join()
