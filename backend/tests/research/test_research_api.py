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
async def research_client(tmp_path: Path, monkeypatch) -> AsyncIterator[AsyncClient]:
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


async def test_research_routes_are_public_in_openapi():
    paths = create_app().openapi()["paths"]
    assert "/api/v1/experiments" in paths
    assert "/api/v1/experiments/{experiment_id}" in paths
    assert "/api/v1/experiments/{experiment_id}/runs" in paths
    assert "/api/v1/experiments/{experiment_id}/comparison" in paths
    assert "/api/v1/experiments/{experiment_id}/research-report" in paths
    assert "/api/v1/research-journal" in paths
    assert "/api/v1/backtests/{run_id}/diagnostics" in paths
    assert "/api/v1/backtests/{run_id}/research-report" in paths


async def test_create_and_list_experiment(research_client):
    created = await research_client.post(
        "/api/v1/experiments",
        json={"name": "exp", "hypothesis": "h", "tags": ["a"]},
    )
    assert created.status_code == 201
    payload = created.json()
    assert payload["name"] == "exp"
    assert payload["status"] == "DRAFT"
    listed = await research_client.get("/api/v1/experiments")
    assert listed.status_code == 200
    assert any(item["id"] == payload["id"] for item in listed.json()["items"])


async def test_experiment_not_found_returns_404(research_client):
    response = await research_client.get("/api/v1/experiments/missing")
    assert response.status_code == 404
    assert response.json()["error_code"] == "EXPERIMENT_NOT_FOUND"


async def test_journal_create_and_read(research_client):
    created = await research_client.post(
        "/api/v1/research-journal",
        json={"title": "note", "entry_type": "OBSERVATION", "content": "text", "tags": []},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    fetched = await research_client.get(f"/api/v1/research-journal/{entry_id}")
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "text"
