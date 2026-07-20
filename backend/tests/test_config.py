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
    assert settings.import_directory == tmp_path / "imports" / "staging"


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


def test_runtime_root_rebases_relative_runtime_paths(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    runtime_root = tmp_path / "runtime"

    settings = Settings(project_root=project_root, runtime_root=runtime_root)

    assert settings.runtime_root == runtime_root.resolve()
    assert settings.sqlite_path == runtime_root / "data" / "quant_lab.db"
    assert settings.duckdb_path == runtime_root / "data" / "analytics.duckdb"
    assert settings.log_path == runtime_root / "logs" / "quant-lab.jsonl"
    assert settings.run_directory == runtime_root / ".run"
    assert settings.import_directory == runtime_root / "imports" / "staging"


def test_relative_runtime_root_is_anchored_to_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    settings = Settings(project_root=project_root, runtime_root=Path("runtime/local"))

    expected_root = (project_root / "runtime" / "local").resolve()
    assert settings.runtime_root == expected_root
    assert settings.sqlite_path == expected_root / "data" / "quant_lab.db"
    assert settings.duckdb_path == expected_root / "data" / "analytics.duckdb"
    assert settings.log_path == expected_root / "logs" / "quant-lab.jsonl"
    assert settings.run_directory == expected_root / ".run"
    assert settings.import_directory == expected_root / "imports" / "staging"


def test_absolute_runtime_path_is_not_rebased(tmp_path: Path) -> None:
    absolute_database = tmp_path / "explicit" / "quant.db"
    settings = Settings(
        project_root=tmp_path / "project",
        runtime_root=tmp_path / "runtime",
        sqlite_path=absolute_database,
    )

    assert settings.sqlite_path == absolute_database.resolve()


def test_windows_runtime_root_is_parsed_without_project_prefix(tmp_path: Path) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=Path("D:/WIL_QUANT_RUNTIME"))

    assert str(settings.runtime_root).replace("\\", "/") == "D:/WIL_QUANT_RUNTIME"
