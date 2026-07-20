from pathlib import Path

import pytest
from pydantic import ValidationError

from quant_lab.core.config import RunMode, Settings


def test_defaults_to_research_with_project_local_paths(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)

    assert settings.run_mode is RunMode.RESEARCH
    assert settings.sqlite_path == tmp_path / "data" / "quant_lab.db"
    assert settings.duckdb_path == tmp_path / "data" / "analytics.duckdb"
    assert settings.log_path == tmp_path / "logs" / "quant-lab.jsonl"
    assert settings.run_directory == tmp_path / ".run"


@pytest.mark.parametrize("mode", ["PAPER", "LIVE"])
def test_phase_one_rejects_non_research_modes(tmp_path: Path, mode: str) -> None:
    with pytest.raises(ValidationError, match="RESEARCH"):
        Settings(project_root=tmp_path, run_mode=mode)


def test_runtime_directories_are_created_under_project_root(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path)

    settings.ensure_runtime_directories()

    assert settings.sqlite_path.parent.is_dir()
    assert settings.duckdb_path.parent.is_dir()
    assert settings.log_path.parent.is_dir()
    assert settings.run_directory.is_dir()
