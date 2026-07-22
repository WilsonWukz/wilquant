from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import quant_lab.datasets.repository as repository_module
from alembic import command
from quant_lab.core.config import Settings
from quant_lab.datasets.persistence import DatasetVersionModel
from quant_lab.datasets.repository import DatasetRepository
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.main import create_app
from quant_lab.market_data.persistence import DataSourceModel, ImportBatchModel

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


def insert_dataset_version(engine: Engine, dataset_id: str) -> str:
    now = datetime(2026, 7, 21, 8, 30, tzinfo=UTC)
    version_id = "version-for-api"
    with Session(engine) as session, session.begin():
        session.add(
            DataSourceModel(
                source_id="source-for-api-version",
                identifier="api-version-source",
                name="API version source",
                source_type="LOCAL_FILE",
                is_local=True,
                version="1",
                original_file="controlled-upload.csv",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ImportBatchModel(
                batch_id="batch-for-api-version",
                data_source_id="source-for-api-version",
                provider_name="local_csv",
                source_name="controlled-upload.csv",
                source_file="controlled-upload.csv",
                source_file_hash="d" * 64,
                requested_at=now,
                status="PREVIEW_READY",
                row_count=1,
                accepted_count=1,
                rejected_count=0,
                warning_count=0,
                schema_version="market-bar@1",
            )
        )
        session.flush()
        session.add(
            DatasetVersionModel(
                dataset_version_id=version_id,
                dataset_id=dataset_id,
                version=1,
                status="VALIDATING",
                source_batch_id="batch-for-api-version",
                source_preview_fingerprint="e" * 64,
                publication_fingerprint="f" * 64,
                schema_version="market-bar@1",
                normalization_version="normalization@1",
                quality_rules_version="quality@1",
                publication_format_version="parquet@1",
                partition_strategy_version="market-bars@1",
                row_count=0,
                instrument_count=0,
                min_timestamp=now,
                max_timestamp=now,
                partition_count=0,
                file_count=0,
                total_size_bytes=0,
                quality_issue_count=0,
                warning_count=0,
                blocking_issue_count=0,
                publication_claimed_at=now,
                published_at=now,
                created_at=now,
            )
        )
    return version_id


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
    assert first.json()["created_at"].endswith(("Z", "+00:00"))
    assert first.json()["updated_at"].endswith(("Z", "+00:00"))
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
    assert datasets.json()["items"][0]["created_at"].endswith(("Z", "+00:00"))
    assert datasets.json()["items"][0]["updated_at"].endswith(("Z", "+00:00"))
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


async def test_version_api_datetimes_are_explicit_utc(
    dataset_client: AsyncClient,
    tmp_path: Path,
) -> None:
    created = await dataset_client.post("/api/v1/datasets", json=CREATE_DATASET)
    dataset_id = created.json()["dataset_id"]
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    engine = create_sqlite_engine(settings)
    try:
        version_id = insert_dataset_version(engine, dataset_id)
    finally:
        engine.dispose()

    listed = await dataset_client.get(f"/api/v1/datasets/{dataset_id}/versions")
    fetched = await dataset_client.get(
        f"/api/v1/datasets/{dataset_id}/versions/{version_id}"
    )

    assert listed.status_code == fetched.status_code == 200
    for version in (listed.json()["items"][0], fetched.json()):
        for field in (
            "publication_claimed_at",
            "created_at",
            "min_timestamp",
            "max_timestamp",
            "published_at",
        ):
            assert version[field].endswith(("Z", "+00:00"))


async def test_dataset_key_identity_conflict_is_stable_and_redacted(
    dataset_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await dataset_client.post("/api/v1/datasets", json=CREATE_DATASET)
    dataset_key = created.json()["dataset_key"]
    monkeypatch.setattr(repository_module, "dataset_key_for", lambda _identity: dataset_key)

    response = await dataset_client.post(
        "/api/v1/datasets",
        json={**CREATE_DATASET, "market": "HK_EQUITY", "name": "different identity"},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "DATASET_IDENTITY_CONFLICT"
    assert response.json()["request_id"]
    assert "HK_EQUITY" not in response.text
    assert "database" not in response.text.lower()
    assert "runtime" not in response.text.lower()


def test_openapi_contains_exact_dataset_routes() -> None:
    paths = create_app().openapi()["paths"]

    assert {path for path in paths if path.startswith("/api/v1/datasets")} == {
        "/api/v1/datasets",
        "/api/v1/datasets/{dataset_id}/versions",
        "/api/v1/datasets/{dataset_id}/versions/{version_id}",
        "/api/v1/datasets/{dataset_id}/versions/{version_id}/summary",
        "/api/v1/datasets/{dataset_id}/versions/{version_id}/bars",
    }
    assert "/api/v1/data-batches/{batch_id}/publish" in paths
    assert "post" in paths["/api/v1/datasets"]
    assert "get" in paths["/api/v1/datasets"]
    assert "get" in paths["/api/v1/datasets/{dataset_id}/versions"]
    assert "get" in paths["/api/v1/datasets/{dataset_id}/versions/{version_id}"]
