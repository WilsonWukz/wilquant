from pathlib import Path

import duckdb
import pytest

from quant_lab.core.config import Settings
from quant_lab.db.duckdb import DuckDbStore
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.health.service import HealthService


def test_duckdb_probe_uses_local_database(tmp_path: Path) -> None:
    store = DuckDbStore(tmp_path / "analytics.duckdb")

    assert store.probe() is True


def test_duckdb_probe_propagates_open_failure(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    store = DuckDbStore(blocked)

    with pytest.raises(duckdb.IOException):
        store.probe()


def test_health_service_redacts_failed_dependency_path(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)
    engine = create_sqlite_engine(settings)
    blocked = tmp_path / "private" / "analytics.duckdb"
    blocked.mkdir(parents=True)
    service = HealthService(engine, DuckDbStore(blocked))

    result = service.readiness()

    assert result.ready is False
    assert {component.name for component in result.components} == {"sqlite", "duckdb"}
    duckdb_component = next(item for item in result.components if item.name == "duckdb")
    assert duckdb_component.status == "unhealthy"
    assert str(blocked) not in duckdb_component.message
    engine.dispose()
