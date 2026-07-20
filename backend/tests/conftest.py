from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine

from quant_lab.core.config import Settings
from quant_lab.db.duckdb import DuckDbStore
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.health.service import HealthService
from quant_lab.main import create_app


async def _test_client(
    settings: Settings,
    engine: Engine,
    duckdb_path: Path,
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, HealthService(engine, DuckDbStore(duckdb_path)))
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        yield client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    settings = Settings(project_root=tmp_path)
    engine = create_sqlite_engine(settings)
    try:
        async for test_client in _test_client(settings, engine, settings.duckdb_path):
            yield test_client
    finally:
        engine.dispose()


@pytest.fixture
async def unready_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    settings = Settings(project_root=tmp_path)
    engine = create_sqlite_engine(settings)
    blocked_path = tmp_path / "private" / "analytics.duckdb"
    blocked_path.mkdir(parents=True)
    try:
        async for test_client in _test_client(settings, engine, blocked_path):
            yield test_client
    finally:
        engine.dispose()
