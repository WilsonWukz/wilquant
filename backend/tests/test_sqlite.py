from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine, probe_sqlite


def test_initial_migration_creates_app_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    settings = Settings(project_root=tmp_path)
    alembic_config = Config("backend/alembic.ini")

    command.upgrade(alembic_config, "head")
    command.upgrade(alembic_config, "head")

    engine = create_sqlite_engine(settings)
    assert "app_metadata" in inspect(engine).get_table_names()
    assert probe_sqlite(engine) is True
    engine.dispose()
