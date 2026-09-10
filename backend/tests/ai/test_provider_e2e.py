from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import uvicorn

from quant_lab.ai.provider_execution import AIProviderExecutionService
from quant_lab.ai_provider_client import AIProviderHostClient
from quant_lab.ai_provider_host import FakeProvider, OpenAICompatibleProvider, create_app
from quant_lab.ai_provider_host.secrets import MemorySecretStore
from quant_lab.ai_provider_protocol import EndpointProfile, ProviderCapabilities

from .test_provenance_service import provenance as provenance
from .test_provider_execution import make_execution_context


@contextmanager
def running_host(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline and thread.is_alive():
            time.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


@pytest.mark.parametrize("mode", ["fake", "max_tokens", "max_completion_tokens"])
def test_core_host_provider_two_http_boundaries(provenance, tmp_path, mode):
    seen = []
    upstream_secret = "private-upstream-test-value"

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.headers["Authorization"] == f"Bearer {upstream_secret}"
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(data)
            result = {
                "id": "upstream-id",
                "model": "test",
                "choices": [
                    {
                        "message": {
                            "content": '{"status":"ok"}',
                            "reasoning_content": "must-not-persist",
                            "api_key": upstream_secret,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            }
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    try:
        profile = EndpointProfile(
            profile_id="e2e",
            model="test",
            base_url=f"http://127.0.0.1:{upstream.server_port}/v1",
            credential_ref="wilquant.ai.test",
            allow_local_http=True,
            capabilities=ProviderCapabilities(
                output_token_parameter=("max_tokens" if mode == "fake" else mode)
            ),
        )
        store = MemorySecretStore()
        store.set(profile.credential_ref, upstream_secret)
        provider = (
            FakeProvider(profile) if mode == "fake" else OpenAICompatibleProvider(profile, store)
        )
        token = secrets.token_urlsafe(32)
        token_path = tmp_path / "test-token"
        token_path.write_text(token)
        context = make_execution_context(provenance, tmp_path, profile)
        _, _, authorized, messages, artifact_root = context
        if mode == "fake":
            from quant_lab.ai_provider_smoke import smoke_context

            authorized, messages = smoke_context(provenance.repository, profile)
        with running_host(create_app(profile, provider, token)) as url:
            client = AIProviderHostClient(url, token_path)
            assert client.health()["status"] in {"ready", "healthy"}
            service = AIProviderExecutionService(provenance.repository, client, artifact_root)
            attempt = service.execute(authorized, messages)
            assert attempt.status == "COMPLETED", attempt.failure_code
            assert attempt.output_fingerprint
        usage = provenance.list_usage(attempt.run_id)
        assert len(usage) == 1 and usage[0].total_tokens is not None
        if mode != "fake":
            assert len(seen) == 1
            assert seen[0][mode] == 20
            assert "tools" not in seen[0] and seen[0].get("stream", False) is False
        else:
            assert seen == [] and provider.invocation_count == 1
        for path in (tmp_path / "ai").rglob("*.json"):
            data = path.read_text()
            assert "must-not-persist" not in data
            assert upstream_secret not in data and token not in data
        serialized = json.dumps([t.payload_json for t in provenance.list_trace(attempt.run_id)])
        assert "candidate_only" in serialized
        assert upstream_secret not in serialized
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
