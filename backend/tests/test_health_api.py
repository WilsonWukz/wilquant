import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_liveness_does_not_require_databases(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readiness_reports_research_components(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["run_mode"] == "RESEARCH"
    assert body["application_version"] == "0.1.0"
    assert {item["name"] for item in body["components"]} == {"sqlite", "duckdb"}
    assert all(item["status"] == "healthy" for item in body["components"])


async def test_readiness_returns_503_without_leaking_path(unready_client: AsyncClient) -> None:
    response = await unready_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "OneDrive" not in response.text
    assert "private" not in response.text
