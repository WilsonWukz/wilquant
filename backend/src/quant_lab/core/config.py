from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


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
    runtime_root: Path | None = None
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
    import_directory: Path = Path("imports/staging")
    publication_staging_directory: Path = Path("data/publication-staging")
    published_directory: Path = Path("data/published")
    import_max_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    import_preview_rows: int = Field(default=100, ge=1, le=1000)
    log_level: str = "INFO"

    @field_validator("runtime_root", mode="before")
    @classmethod
    def empty_runtime_root_means_default(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @model_validator(mode="after")
    def validate_phase_one_and_resolve_paths(self) -> Self:
        if self.run_mode is not RunMode.RESEARCH:
            raise ValueError("Phase 1 only permits RESEARCH run mode")

        self.project_root = self.project_root.expanduser().resolve()
        if self.runtime_root is not None:
            runtime_root = self.runtime_root.expanduser()
            if not runtime_root.is_absolute():
                runtime_root = self.project_root / runtime_root
            self.runtime_root = runtime_root.resolve()
        path_root = self.runtime_root or self.project_root
        for field_name in (
            "sqlite_path",
            "duckdb_path",
            "log_path",
            "run_directory",
            "import_directory",
            "publication_staging_directory",
            "published_directory",
        ):
            path = getattr(self, field_name).expanduser()
            if not path.is_absolute():
                path = path_root / path
            setattr(self, field_name, path.resolve())
        return self

    def ensure_runtime_directories(self) -> None:
        """Create only directories needed by configured local runtime files."""

        directories = {
            self.sqlite_path.parent,
            self.duckdb_path.parent,
            self.log_path.parent,
            self.run_directory,
            self.import_directory,
            self.publication_staging_directory,
            self.published_directory,
        }
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    @property
    def sqlite_url(self) -> str:
        """Return a SQLAlchemy URL without string-concatenating a filesystem path."""

        return URL.create("sqlite+pysqlite", database=str(self.sqlite_path)).render_as_string(
            hide_password=False
        )
