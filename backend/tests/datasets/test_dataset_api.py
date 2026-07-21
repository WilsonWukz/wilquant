from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.main import create_app

pytestmark = pytest.mark.anyio


CREATE_DATASET = {
    "logical_key": "cn-a-share-daily-bars",
    "name": "A股日线",
    "description": "研究用规范化日线",
    "dataset_type": "MARKET_BARS",
    "market": "CN_A_SHARE",
    "frequency": "DAILY",
    "adjustment_type": "NONE",
    "schema_version": "market-bar@1",
}


@pytest.fixture
async def dataset_client(tmp_path: Path, monkeypatch) -> AsyncIterator[AsyncClient]:
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


async def test_create_dataset_is_idempotent_by_logical_identity(
    dataset_client: AsyncClient,
) -> None:
    first = await dataset_client.post("/api/v1/datasets", json=CREATE_DATASET)
    second = await dataset_client.post(
        "/api/v1/datasets",
        json={
            **CREATE_DATASET,
            "name": "Renamed display label",
            "description": "Changed display description",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert first.json()["dataset_key"]
    assert first.json()["name"] == "A股日线"
    assert "runtime" not in first.text


async def test_list_and_empty_version_routes_are_safe(
    dataset_client: AsyncClient,
) -> None:
    assert (await dataset_client.get("/api/v1/datasets")).json() == {"items": []}
    created = await dataset_client.post("/api/v1/datasets", json=CREATE_DATASET)
    dataset_id = created.json()["dataset_id"]

    datasets = await dataset_client.get("/api/v1/datasets")
    versions = await dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions")
    missing = await dataset_client.get(
        f"/api/v1/datasets/{dataset_id}/versions/missing-version"
    )

    assert datasets.status_code == 200
    assert datasets.json()["items"] == [created.json()]
    assert versions.status_code == 200
    assert versions.json() == {"items": []}
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "DATASET_VERSION_NOT_FOUND"
    assert "database" not in missing.text.lower()
    assert "runtime" not in missing.text.lower()


async def test_rejects_invalid_logical_key_with_stable_safe_error(
    dataset_client: AsyncClient,
) -> None:
    response = await dataset_client.post(
        "/api/v1/datasets",
        json={**CREATE_DATASET, "logical_key": "../../sensitive"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_DATASET_IDENTITY"
    assert response.json()["request_id"]
    assert "sensitive" not in response.text
    assert ".." not in response.text


async def test_database_errors_are_redacted(
    dataset_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create(*_args, **_kwargs):
        raise SQLAlchemyError(r"database failed at F:\runtime\quant_lab.db")

    monkeypatch.setattr(DatasetRepository, "create_or_get", fail_create)

    response = await dataset_client.post("/api/v1/datasets", json=CREATE_DATASET)

    assert response.status_code == 500
    assert response.json()["error_code"] == "DATABASE_ERROR"
    assert response.json()["request_id"]
    assert "quant_lab.db" not in response.text
    assert "runtime" not in response.text


def test_openapi_contains_exact_dataset_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert {path for path in paths if path.startswith("/api/v1/datasets")} == {
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}/versions",
        "/api/v1/datasets/{dataset_id}/versions/{version_id}",
    }
    assert "post" in paths["/api/v1/datasets"]
    assert "get" in paths["/api/v1/datasets"]
    assert "get" in paths["/api/v1/datasets/{dataset_id}/versions"]
    assert "get" in paths["/api/v1/datasets/{dataset_id}/versions/{version_id}"]
