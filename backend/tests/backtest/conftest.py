from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine
from quant_lab.market_data.calendar_persistence import TradingCalendarRepository


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path)
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    engine = create_sqlite_engine(settings)
    config = Config("backend/alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.sqlite_url)
    command.upgrade(config, "head")
    try:
        yield engine, TradingCalendarRepository(engine)
    finally:
        engine.dispose()
