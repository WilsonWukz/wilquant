from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def strategy_client(tmp_path: Path, monkeypatch) -> AsyncIterator[AsyncClient]:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


async def test_strategy_routes_are_public_in_openapi():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/strategies" in paths
    assert "/api/v1/strategies/{strategy_id}" in paths
    assert "/api/v1/strategies/{strategy_id}/versions" in paths
    assert "/api/v1/strategies/{strategy_id}/archive" in paths


async def test_strategy_definition_response_schema_is_stable(strategy_client):
    response = await strategy_client.post(
        "/api/v1/strategies",
        json={"name": "momentum", "description": "desc", "strategy_type": "BUY_AND_HOLD"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {
        "id",
        "name",
        "description",
        "strategy_type",
        "status",
        "created_at",
        "updated_at",
    }
    assert payload["strategy_type"] == "BUY_AND_HOLD"
    assert payload["status"] == "ACTIVE"


async def test_strategy_version_response_schema_is_stable(strategy_client):
    created = await strategy_client.post(
        "/api/v1/strategies",
        json={"name": "momentum", "description": "desc", "strategy_type": "BUY_AND_HOLD"},
    )
    strategy_id = created.json()["id"]
    response = await strategy_client.post(
        f"/api/v1/strategies/{strategy_id}/versions",
        json={"strategy_spec": {"instrument_id": "600000.XSHG"}, "change_note": "first"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert set(payload) == {
        "id",
        "strategy_definition_id",
        "version",
        "strategy_spec",
        "strategy_fingerprint",
        "change_note",
        "created_at",
    }
    assert payload["strategy_spec"] == {"instrument_id": "600000.XSHG"}
    assert len(payload["strategy_fingerprint"]) == 64


async def test_strategy_not_found_returns_404_not_500(strategy_client):
    response = await strategy_client.get("/api/v1/strategies/missing")
    assert response.status_code == 404
    assert response.json()["error_code"] == "STRATEGY_NOT_FOUND"


async def test_unsafe_strategy_spec_returns_400_not_500(strategy_client):
    created = await strategy_client.post(
        "/api/v1/strategies",
        json={"name": "momentum", "description": "desc", "strategy_type": "BUY_AND_HOLD"},
    )
    strategy_id = created.json()["id"]
    response = await strategy_client.post(
        f"/api/v1/strategies/{strategy_id}/versions",
        json={"strategy_spec": {"config": {"python": "print(1)"}}, "change_note": ""},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "STRATEGY_SPEC_INVALID"


async def test_archived_strategy_rejects_new_version(strategy_client):
    created = await strategy_client.post(
        "/api/v1/strategies",
        json={"name": "momentum", "description": "desc", "strategy_type": "BUY_AND_HOLD"},
    )
    strategy_id = created.json()["id"]
    await strategy_client.post(f"/api/v1/strategies/{strategy_id}/archive")
    response = await strategy_client.post(
        f"/api/v1/strategies/{strategy_id}/versions",
        json={"strategy_spec": {"instrument_id": "600000.XSHG"}, "change_note": ""},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "STRATEGY_ARCHIVED"
