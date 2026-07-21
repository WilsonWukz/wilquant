import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.main import create_app
from quant_lab.market_data.service import MarketDataImportService
from quant_lab.market_data.versions import (
    NORMALIZATION_RULES_VERSION,
    PREVIEW_FINGERPRINT_VERSION,
    QUALITY_RULES_VERSION,
    SCHEMA_VERSION,
)

pytestmark = pytest.mark.anyio

VALID_CSV = (
    b"symbol,exchange,trade_date,open,high,low,close,volume,amount\n"
    b"600000,XSHG,2026-07-17,10.1,10.8,10.0,10.5,1200,12500.25\n"
    b"000001,XSHE,2026-07-17,10.1,9.0,10.0,10.5,0,0\n"
)
MAPPING = {
    field: field
    for field in (
        "symbol",
        "exchange",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    )
}


@pytest.fixture
async def import_client(tmp_path: Path, monkeypatch) -> AsyncIterator[AsyncClient]:
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


async def inspect_csv(client: AsyncClient, content: bytes = VALID_CSV):
    return await client.post(
        "/api/v1/data/imports/inspect",
        params={"filename": "bars.csv"},
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )


async def test_inspect_preview_and_read_batch(
    import_client: AsyncClient,
    caplog,
) -> None:
    caplog.set_level(logging.INFO)
    inspection = await inspect_csv(import_client)

    assert inspection.status_code == 201
    inspected = inspection.json()
    assert inspected["provider_name"] == "local_csv"
    assert inspected["row_count"] == 2
    assert inspected["suggested_mapping"] == MAPPING
    assert len(inspected["source_file_hash"]) == 64
    assert "runtime" not in inspection.text

    preview = await import_client.post(
        "/api/v1/data/imports/preview",
        json={"batch_id": inspected["batch_id"], "field_mapping": MAPPING},
    )
    assert preview.status_code == 200
    result = preview.json()
    assert result["status"] == "PREVIEW_READY"
    assert result["row_count"] == 2
    assert result["accepted_count"] == 1
    assert result["rejected_count"] == 1
    assert result["warning_count"] == 0
    assert len(result["sample_rows"]) == 1
    assert len(result["preview_fingerprint"]) == 64
    assert result["provider_version"] == "local-csv@1"
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["normalization_version"] == NORMALIZATION_RULES_VERSION
    assert result["quality_rules_version"] == QUALITY_RULES_VERSION
    assert result["preview_fingerprint_version"] == PREVIEW_FINGERPRINT_VERSION
    assert result["preview_completed_at"].endswith("Z")
    assert result["publish_eligibility"] == "ELIGIBLE"

    batch = await import_client.get(f"/api/v1/data/imports/{inspected['batch_id']}")
    issues = await import_client.get(
        f"/api/v1/data/imports/{inspected['batch_id']}/issues"
    )
    assert batch.json()["status"] == "PREVIEW_READY"
    assert batch.json()["preview_fingerprint"] == result["preview_fingerprint"]
    assert batch.json()["publish_eligibility"] == "ELIGIBLE"
    assert any(item["issue_code"] == "HIGH_BELOW_LOW" for item in issues.json()["items"])
    issue = next(item for item in issues.json()["items"] if item["issue_code"] == "HIGH_BELOW_LOW")
    assert issue["issue_fingerprint_version"] == "quality-issue-sha256@2"
    assert issue["normalized_value"] is not None
    assert any(
        getattr(record, "event", None) == "data_import.preview_ready"
        and getattr(record, "batch_id", None) == inspected["batch_id"]
        and getattr(record, "rejected_count", None) == 1
        for record in caplog.records
    )


async def test_duplicate_hash_is_rejected(import_client: AsyncClient) -> None:
    assert (await inspect_csv(import_client)).status_code == 201

    duplicate = await inspect_csv(import_client)

    assert duplicate.status_code == 409
    assert duplicate.json()["error_code"] == "DUPLICATE_SOURCE"


async def test_repeated_preview_is_idempotent(import_client: AsyncClient) -> None:
    inspection = await inspect_csv(import_client)
    batch_id = inspection.json()["batch_id"]

    first_preview = await import_client.post(
        "/api/v1/data/imports/preview",
        json={"batch_id": batch_id, "field_mapping": MAPPING},
    )
    first_issues = await import_client.get(f"/api/v1/data/imports/{batch_id}/issues")
    second_preview = await import_client.post(
        "/api/v1/data/imports/preview",
        json={"batch_id": batch_id, "field_mapping": MAPPING},
    )
    second_issues = await import_client.get(f"/api/v1/data/imports/{batch_id}/issues")

    assert first_preview.status_code == second_preview.status_code == 200
    stable_fields = (
        "row_count",
        "accepted_count",
        "rejected_count",
        "warning_count",
        "preview_fingerprint",
        "provider_version",
        "schema_version",
        "normalization_version",
        "quality_rules_version",
        "preview_fingerprint_version",
    )
    assert {field: first_preview.json()[field] for field in stable_fields} == {
        field: second_preview.json()[field] for field in stable_fields
    }
    assert first_issues.json() == second_issues.json()
    assert len(second_issues.json()["items"]) == len(first_issues.json()["items"])


async def test_legacy_preview_ready_batch_requires_a_new_preview(
    import_client: AsyncClient,
    tmp_path: Path,
) -> None:
    inspection = await inspect_csv(import_client)
    batch_id = inspection.json()["batch_id"]
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    engine = create_sqlite_engine(settings)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE import_batches SET status = 'PREVIEW_READY', "
                "source_file_size = NULL, field_mapping_json = NULL, "
                "provider_version = NULL, normalization_version = NULL, "
                "quality_rules_version = NULL, preview_fingerprint_version = NULL, "
                "preview_fingerprint = NULL, preview_completed_at = NULL "
                "WHERE batch_id = :batch_id"
            ),
            {"batch_id": batch_id},
        )
    engine.dispose()

    response = await import_client.get(f"/api/v1/data/imports/{batch_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "PREVIEW_READY"
    assert payload["publish_eligibility"] == "PREVIEW_REQUIRED"
    assert payload["preview_fingerprint"] is None
    assert "runtime" not in response.text
    assert str(tmp_path) not in response.text


async def test_all_parse_failures_are_not_reported_as_an_empty_file(
    import_client: AsyncClient,
) -> None:
    malformed = VALID_CSV.replace(b"10.1,10.8", b"not-a-price,10.8").splitlines()[:2]
    inspection = await inspect_csv(import_client, b"\n".join(malformed) + b"\n")
    batch_id = inspection.json()["batch_id"]

    preview = await import_client.post(
        "/api/v1/data/imports/preview",
        json={"batch_id": batch_id, "field_mapping": MAPPING},
    )
    issues = await import_client.get(f"/api/v1/data/imports/{batch_id}/issues")

    assert preview.status_code == 200
    assert preview.json()["row_count"] == 1
    assert preview.json()["rejected_count"] == 1
    assert {item["issue_code"] for item in issues.json()["items"]} == {
        "TYPE_PARSE_ERROR"
    }


@pytest.mark.parametrize(
    ("filename", "expected_code"),
    [("../bars.csv", "INVALID_FILENAME"), ("bars.exe", "UNSUPPORTED_FORMAT")],
)
async def test_rejects_unsafe_filename_or_format(
    import_client: AsyncClient,
    filename: str,
    expected_code: str,
) -> None:
    response = await import_client.post(
        "/api/v1/data/imports/inspect",
        params={"filename": filename},
        content=b"data",
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == expected_code
    assert "OneDrive" not in response.text


async def test_rejects_oversized_upload(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        project_root=tmp_path,
        runtime_root=tmp_path / "runtime",
        import_max_bytes=4,
    )
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        response = await client.post(
            "/api/v1/data/imports/inspect",
            params={"filename": "bars.csv"},
            content=b"12345",
        )

    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (SQLAlchemyError("sensitive D:\\runtime\\quant_lab.db"), "DATABASE_ERROR"),
        (RuntimeError("sensitive internal detail"), "INTERNAL_ERROR"),
    ],
)
async def test_inspect_returns_stable_redacted_server_errors(
    import_client: AsyncClient,
    monkeypatch,
    error: Exception,
    expected_code: str,
) -> None:
    def fail_inspection(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(MarketDataImportService, "inspect", fail_inspection)

    response = await inspect_csv(import_client)

    assert response.status_code == 500
    assert response.json()["error_code"] == expected_code
    assert response.json()["request_id"]
    assert "sensitive" not in response.text
    assert "runtime" not in response.text
