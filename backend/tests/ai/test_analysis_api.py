import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .test_ai2_concrete_resolvers import domain_registry as domain_registry
from .test_analysis_orchestration import setup_analysis


def api(service):
    from quant_lab.ai.analysis_access import AnalysisAccessBoundary
    from quant_lab.api.ai_analyses import router

    app = FastAPI()
    app.state.ai_analysis_service = service
    app.state.ai_analysis_access_token = "a" * 64
    app.state.ai_analysis_origins = {"http://127.0.0.1:5173"}
    app.add_middleware(AnalysisAccessBoundary)
    app.include_router(router, prefix="/api/v1/ai")
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))


def test_api_execute_and_default_result_are_not_raw_proxy(domain_registry, tmp_path):
    service, run_id, _provider, _repo = setup_analysis(domain_registry, tmp_path)
    with api(service) as client:
        headers = {"Authorization": "Bearer " + "a" * 64}
        response = client.post(
            f"/api/v1/ai/analyses/{run_id}/execute",
            headers=headers,
            json={"idempotency_key": "execute", "intent": "INITIAL"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["outcome"] == "PROCEEDED"
        assert result["diagnosis"] and result["recommendation"]
        assert "prompt_artifact" not in response.text
        assert "reasoning_content" not in response.text
        assert len(result["attempts"]) == 2
        assert len(result["usage"]) == 2
        assert client.get(f"/api/v1/ai/analyses/{run_id}", headers=headers).status_code == 200
        assert client.post("/api/v1/ai/completions", headers=headers, json={}).status_code == 404


@pytest.mark.parametrize(
    "headers,status",
    [
        ({}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Authorization": "Bearer " + "a" * 64, "Origin": "https://evil.example"}, 403),
        ({"Authorization": "Bearer " + "a" * 64, "Host": "evil.example"}, 403),
    ],
)
def test_cost_boundary_blocks_unauthorized_sources_before_call(
    domain_registry, tmp_path, headers, status
):
    service, run_id, provider, _repo = setup_analysis(domain_registry, tmp_path)
    with api(service) as client:
        response = client.post(
            f"/api/v1/ai/analyses/{run_id}/execute",
            headers=headers,
            json={"idempotency_key": "execute", "intent": "INITIAL"},
        )
        assert response.status_code == status
        assert not provider.requests


def test_create_idempotency_and_strict_fields(domain_registry, tmp_path):
    service, run_id, provider, _repo = setup_analysis(domain_registry, tmp_path)
    import json

    original = service.store.read(json.loads(service.analyses.get(run_id).request_artifact_json))
    payload = {"idempotency_key": "api-create", "request": original}
    headers = {"Authorization": "Bearer " + "a" * 64}
    with api(service) as client:
        first = client.post("/api/v1/ai/analyses", json=payload, headers=headers)
        assert first.status_code == 201, first.text
        same = client.post("/api/v1/ai/analyses", json=payload, headers=headers)
        assert same.json()["id"] == first.json()["id"]
        original["research_question"] = "另一研究问题"
        assert client.post("/api/v1/ai/analyses", json=payload, headers=headers).status_code == 409
        original["tools"] = []
        assert client.post("/api/v1/ai/analyses", json=payload, headers=headers).status_code == 422
        original["credential"] = "never-echo-this-secret"
        assert (
            "never-echo-this-secret"
            not in client.post("/api/v1/ai/analyses", json=payload, headers=headers).text
        )
        assert (
            client.post(
                f"/api/v1/ai/analyses/{run_id}/execute", content="{}", headers=headers
            ).status_code
            == 415
        )
        assert (
            client.post(f"/api/v1/ai/analyses/{run_id}/cancel", json={}, headers=headers).json()[
                "outcome"
            ]
            == "CANCELLED"
        )
        assert not provider.requests
