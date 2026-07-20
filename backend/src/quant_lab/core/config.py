from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RunMode(StrEnum):
    """Declared platform modes.

    Phase 1 intentionally enables only RESEARCH.
    """

    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE = "LIVE"


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Validated process configuration with project-local defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="QUANT_LAB_",
        extra="ignore",
        validate_default=True,
    )

    project_root: Path = Field(default_factory=_default_project_root)
    run_mode: RunMode = RunMode.RESEARCH
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    frontend_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    sqlite_path: Path = Path("data/quant_lab.db")
    duckdb_path: Path = Path("data/analytics.duckdb")
    log_path: Path = Path("logs/quant-lab.jsonl")
    run_directory: Path = Path(".run")
    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_phase_one_and_resolve_paths(self) -> Self:
        if self.run_mode is not RunMode.RESEARCH:
            raise ValueError("Phase 1 only permits RESEARCH run mode")

        self.project_root = self.project_root.expanduser().resolve()
        for field_name in ("sqlite_path", "duckdb_path", "log_path", "run_directory"):
            path = getattr(self, field_name).expanduser()
            if not path.is_absolute():
                path = self.project_root / path
            setattr(self, field_name, path.resolve())
        return self

    def ensure_runtime_directories(self) -> None:
        """Create only directories needed by configured local runtime files."""

        directories = {
            self.sqlite_path.parent,
            self.duckdb_path.parent,
            self.log_path.parent,
            self.run_directory,
        }
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
