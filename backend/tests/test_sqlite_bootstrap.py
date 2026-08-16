from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "backend" / "src"
ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"

REVISION_0008 = "20260722_0008"
REVISION_HEAD = "20260722_0009"


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def _runtime_settings(tmp_path: Path) -> Settings:
    """Point every runtime path at a fresh nested root that starts empty."""
    return Settings(project_root=tmp_path, runtime_root=tmp_path / "nested" / "runtime")


def _backtest_columns(engine) -> set[str]:
    with engine.connect() as connection:
        return {row[1] for row in connection.execute(text("PRAGMA table_info(backtest_runs)"))}


def _trigger_names(engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }


def test_import_has_no_filesystem_side_effect(tmp_path: Path) -> None:
    project_root = tmp_path / "absent-root"
    env = os.environ.copy()
    env["QUANT_LAB_PROJECT_ROOT"] = str(project_root)
    env["PYTHONPATH"] = str(SRC_DIR)
    code = "import quant_lab.core.config, quant_lab.db, quant_lab.db.sqlite; print('imported')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert not project_root.exists()


def test_fresh_nested_migration_creates_only_the_database_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))

    assert not settings.sqlite_path.parent.exists()

    command.upgrade(_alembic_config(), "head")

    assert settings.sqlite_path.exists()
    assert not settings.published_directory.exists()
    assert not settings.publication_staging_directory.exists()
    assert not settings.import_directory.exists()


def test_upgrade_to_head_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))

    config = _alembic_config()
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_sqlite_engine(settings)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    engine.dispose()


def test_0008_binds_strategy_versions_and_downgrades_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _runtime_settings(tmp_path)
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = _alembic_config()

    command.upgrade(config, REVISION_0008)
    engine = create_sqlite_engine(settings)
    assert "strategy_versions" in inspect(engine).get_table_names()
    assert "strategy_version_id" not in _backtest_columns(engine)
    assert "trg_strategy_versions_immutable" in _trigger_names(engine)

    command.upgrade(config, REVISION_HEAD)
    assert "strategy_version_id" in _backtest_columns(engine)
    assert "trg_strategy_versions_immutable" in _trigger_names(engine)
    assert "trg_backtest_runs_succeeded_no_update" in _trigger_names(engine)

    command.downgrade(config, REVISION_0008)
    assert "strategy_version_id" not in _backtest_columns(engine)

    command.upgrade(config, REVISION_HEAD)
    assert "strategy_version_id" in _backtest_columns(engine)
    assert "trg_backtest_runs_succeeded_no_update" in _trigger_names(engine)
    engine.dispose()
