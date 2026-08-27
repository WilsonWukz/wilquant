from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from alembic import command
from quant_lab.ai.configuration import (
    AIModelConfigVersionService,
    PromptTemplateVersionService,
)
from quant_lab.ai.repository import AIRepository
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def ai_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncClient, str, str]]:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    repository = AIRepository(engine)
    prompt = PromptTemplateVersionService(repository).publish(
        template_name="diagnosis",
        stage="DIAGNOSIS",
        schema_version="diagnosis@1",
        content="test",
        variable_contract={"required": ["case"]},
        validator_policy_version="validators@1",
        actor="USER",
    )
    model = AIModelConfigVersionService(repository).publish(
        provider_kind="FAKE",
        provider_id="fake",
        base_url_identity="local-fake",
        model_identifier="fake-v1",
        endpoint_profile_id="fake",
        capabilities={},
        parameters={"tool_configuration": "NONE"},
        actor="USER",
    )
    engine.dispose()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client, prompt.id, model.id


def _case_payload() -> dict[str, object]:
    return {
        "purpose": "BACKTEST_REVIEW",
        "market": "CN_A_SHARE",
        "exchange": "SSE",
        "symbol": "600000",
        "instrument_id": "600000.XSHG",
        "asset_type": "EQUITY",
        "currency": "CNY",
        "timeframe": "1D",
        "as_of_utc": "2026-08-27T08:00:00Z",
        "market_local_trade_date": "2026-08-27",
        "bindings": {
            "market_data_fingerprint": "a" * 64,
            "calendar_fingerprint": "b" * 64,
            "market_rules_fingerprint": "c" * 64,
        },
    }


async def test_ai_provenance_routes_are_public_but_low_level_provider_routes_are_absent() -> None:
    paths = create_app().openapi()["paths"]
    expected = {
        "/api/v1/research-cases",
        "/api/v1/research-cases/{case_id}",
        "/api/v1/ai-analysis-runs",
        "/api/v1/ai-analysis-runs/{run_id}",
        "/api/v1/ai-analysis-runs/{run_id}/trace",
        "/api/v1/ai-analysis-runs/{run_id}/usage",
    }
    assert expected.issubset(paths)
    assert not any(
        fragment in path
        for path in paths
        for fragment in ("/attempts", "/complete", "/provider", "/raw", "/orders")
        if path.startswith("/api/v1/ai")
    )


async def test_create_case_and_run_exposes_safe_provenance_only(ai_client) -> None:
    client, prompt_id, model_id = ai_client
    case_response = await client.post("/api/v1/research-cases", json=_case_payload())
    assert case_response.status_code == 201
    case = case_response.json()
    assert len(case["fingerprint"]) == 64

    run_response = await client.post(
        "/api/v1/ai-analysis-runs",
        json={
            "case_id": case["id"],
            "stage": "DIAGNOSIS",
            "prompt_template_version_id": prompt_id,
            "model_config_version_id": model_id,
            "resolved_prompt_fingerprint": "d" * 64,
            "validator_policy_version": "validators@1",
            "validator_policy_fingerprint": "e" * 64,
        },
    )
    assert run_response.status_code == 201
    run = run_response.json()
    assert run["status"] == "CREATED"
    serialized = str(run).lower()
    assert "api_key" not in serialized
    assert "prompt content" not in serialized
    assert "raw_content" not in serialized

    fetched = await client.get(f"/api/v1/ai-analysis-runs/{run['id']}")
    assert fetched.status_code == 200
    trace = await client.get(f"/api/v1/ai-analysis-runs/{run['id']}/trace")
    usage = await client.get(f"/api/v1/ai-analysis-runs/{run['id']}/usage")
    assert trace.json() == {"items": []}
    assert usage.json() == {"items": []}


async def test_requests_forbid_extra_fields_and_not_found_is_safe(ai_client) -> None:
    client, _, _ = ai_client
    response = await client.post(
        "/api/v1/research-cases", json={**_case_payload(), "api_key": "forbidden"}
    )
    assert response.status_code == 422

    missing_case = await client.get("/api/v1/research-cases/missing")
    assert missing_case.status_code == 404
    assert missing_case.json() == {
        "error_code": "AI_CASE_NOT_FOUND",
        "message": "研究案例不存在",
    }
