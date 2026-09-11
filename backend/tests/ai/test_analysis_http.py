"""AI4 acceptance over real loopback sockets; never contact a real model provider."""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from quant_lab.ai.analysis_access import AnalysisAccessBoundary
from quant_lab.ai.analysis_prompts import publish_analysis_prompts
from quant_lab.ai.analysis_service import ResearchAnalysisService
from quant_lab.ai.configuration import AIModelConfigVersionService, PromptTemplateVersionService
from quant_lab.ai.provider_budget import ProviderBudgetPolicy
from quant_lab.ai.repository import AIRepository
from quant_lab.ai_provider_client import AIProviderHostClient
from quant_lab.ai_provider_host import FakeProvider, OpenAICompatibleProvider, create_app
from quant_lab.ai_provider_host.secrets import MemorySecretStore
from quant_lab.ai_provider_protocol import EndpointProfile, ProviderCapabilities
from quant_lab.api.ai_analyses import router

from .test_ai2_concrete_resolvers import domain_registry as domain_registry
from .test_analysis_context import request
from .test_analysis_orchestration import SequencedClient
from .test_provider_e2e import running_host

REASONING_SENTINEL = "private-http-reasoning-must-not-persist"
UPSTREAM_SECRET = "synthetic-local-upstream-credential"


class ContractFakeProvider(FakeProvider):
    """Configure the existing FakeProvider with evidence-bound test candidates only."""

    def __init__(self, profile, modes):
        super().__init__(profile, reasoning_content=REASONING_SENTINEL)
        self.candidates = SequencedClient(modes, profile)

    def complete(self, call):
        self.content = self.candidates.complete(call).content
        return super().complete(call)


def analysis_service(domain_registry, artifact_root, profile, client):
    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    repository = AIRepository(engine)
    first, second = publish_analysis_prompts(PromptTemplateVersionService(repository))
    model = AIModelConfigVersionService(repository).publish(
        provider_kind="OPENAI_COMPATIBLE",
        provider_id=profile.profile_id,
        base_url_identity=profile.base_url,
        model_identifier=profile.model,
        endpoint_profile_id=profile.profile_id,
        capabilities=profile.capabilities.model_dump(mode="json"),
        parameters={
            "provider_profile": profile.model_dump(mode="json"),
            "budget": ProviderBudgetPolicy(
                max_calls=6, max_input_tokens=131072, max_output_tokens=2048
            ).model_dump(mode="json"),
            "max_output_tokens": 2048,
        },
        actor="USER",
    )
    service = ResearchAnalysisService(repository, domain_registry, client, artifact_root)
    payload = request(
        model_config_version_id=model.id,
        stage1_prompt_template_version_id=first.id,
        stage2_prompt_template_version_id=second.id,
    )
    return service, payload


def execute_over_http(domain_registry, tmp_path, profile, provider, outcome, calls):
    token = secrets.token_urlsafe(32)
    token_path = tmp_path / "host-token"
    token_path.write_text(token, encoding="ascii")
    host = create_app(profile, provider, token)
    host_paths = []

    @host.middleware("http")
    async def record_path(incoming, call_next):
        host_paths.append(incoming.url.path)
        return await call_next(incoming)

    with running_host(host) as host_url:
        client = AIProviderHostClient(host_url, token_path)
        service, payload = analysis_service(
            domain_registry, tmp_path / "artifacts", profile, client
        )
        core = FastAPI()
        core.state.ai_analysis_service = service
        core.state.ai_analysis_access_token = "c" * 64
        core.state.ai_analysis_origins = set()
        core.add_middleware(AnalysisAccessBoundary)
        core.include_router(router, prefix="/api/v1/ai")
        with (
            running_host(core) as core_url,
            httpx.Client(
                base_url=core_url,
                headers={"Authorization": "Bearer " + "c" * 64},
                trust_env=False,
                timeout=30,
            ) as api,
        ):
            created = api.post(
                "/api/v1/ai/analyses",
                json={"idempotency_key": "http-create", "request": payload.model_dump(mode="json")},
            )
            assert created.status_code == 201, created.text
            assert host_paths == [], "Creating a research request must not contact Host"
            run_id = created.json()["id"]
            path = f"/api/v1/ai/analyses/{run_id}"
            executed = api.post(
                path + "/execute", json={"idempotency_key": "http-execute", "intent": "INITIAL"}
            )
            assert executed.status_code == 200, executed.text
            result = executed.json()
            assert result["outcome"] == outcome, result
            assert result["progress"] == "TERMINAL"
            assert result["diagnosis"]
            assert bool(result["recommendation"]) == (outcome == "PROCEEDED")
            assert len(result["attempts"]) == calls
            assert len(result["usage"]) == calls
            assert all(attempt["status"] == "COMPLETED" for attempt in result["attempts"])
            assert [attempt["stage"] for attempt in result["attempts"]] == [
                "STAGE_1_DIAGNOSIS",
                "STAGE_2_RECOMMENDATION",
            ][:calls]
            assert len(service.repository.list_validation_results(run_id)) == calls
            assert host_paths == ["/internal/v1/availability"] + ["/internal/v1/complete"] * calls
            for response in (executed, api.get(path)):
                assert response.status_code == 200
                for forbidden in (
                    "prompt_artifact",
                    "candidate_artifact",
                    "raw_response",
                    "reasoning_content",
                    "credential_ref",
                    REASONING_SENTINEL,
                    UPSTREAM_SECRET,
                    token,
                ):
                    assert forbidden not in response.text
            assert (
                api.post(
                    path + "/execute", json={"idempotency_key": "http-execute", "intent": "INITIAL"}
                ).json()
                == result
            )
            assert len(host_paths) == calls + 1
        trace = json.dumps([row.payload_json for row in service.repository.list_trace(run_id)])
        for forbidden in (REASONING_SENTINEL, UPSTREAM_SECRET, token):
            assert forbidden not in trace
            for artifact in (tmp_path / "artifacts").rglob("*.json"):
                assert forbidden not in artifact.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "modes,outcome,calls", [([], "PROCEEDED", 2), (["abstain"], "ABSTAINED", 1)]
)
def test_analysis_core_to_real_http_fake_host(domain_registry, tmp_path, modes, outcome, calls):
    profile = EndpointProfile(
        profile_id="analysis-http-fake",
        model="test",
        base_url="https://example.invalid/v1",
        credential_ref="wilquant.ai.http-test",
    )
    provider = ContractFakeProvider(profile, modes)
    execute_over_http(domain_registry, tmp_path, profile, provider, outcome, calls)
    assert provider.invocation_count == calls


@pytest.mark.parametrize("token_parameter", ["max_tokens", "max_completion_tokens"])
def test_analysis_core_host_local_openai_http_hops(domain_registry, tmp_path, token_parameter):
    seen = []
    candidates = SequencedClient()

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("Authorization"), data))
            candidate = candidates.complete(
                SimpleNamespace(
                    request_id=f"http-{len(seen)}",
                    endpoint_fingerprint="0" * 64,
                    model="test",
                    messages=[SimpleNamespace(**message) for message in data["messages"]],
                )
            )
            encoded = json.dumps(
                {
                    "id": f"upstream-{len(seen)}",
                    "model": "test",
                    "choices": [
                        {
                            "message": {
                                "content": candidate.content,
                                "reasoning_content": REASONING_SENTINEL,
                                "api_key": UPSTREAM_SECRET,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                }
            ).encode()
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
            profile_id="analysis-http-openai",
            model="test",
            base_url=f"http://127.0.0.1:{upstream.server_port}/v1",
            credential_ref="wilquant.ai.http-test",
            allow_local_http=True,
            capabilities=ProviderCapabilities(output_token_parameter=token_parameter),
        )
        store = MemorySecretStore()
        store.set(profile.credential_ref, UPSTREAM_SECRET)
        execute_over_http(
            domain_registry,
            tmp_path,
            profile,
            OpenAICompatibleProvider(profile, store),
            "PROCEEDED",
            2,
        )
        assert len(seen) == 2
        for path, authorization, body in seen:
            assert path == "/v1/chat/completions"
            assert authorization == f"Bearer {UPSTREAM_SECRET}"
            assert body[token_parameter] == 2048
            other = (
                "max_tokens"
                if token_parameter == "max_completion_tokens"
                else "max_completion_tokens"
            )
            assert other not in body
            assert "tools" not in body and body.get("stream", False) is False
        assert json.loads(seen[0][2]["messages"][1]["content"])["DIAGNOSIS"] is None
        assert json.loads(seen[1][2]["messages"][1]["content"])["DIAGNOSIS"]["fingerprint"]
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
