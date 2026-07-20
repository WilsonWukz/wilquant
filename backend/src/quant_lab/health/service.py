from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine

from quant_lab.db.duckdb import DuckDbStore
from quant_lab.db.sqlite import probe_sqlite

logger = logging.getLogger(__name__)

ComponentName = Literal["sqlite", "duckdb"]
ComponentStatus = Literal["healthy", "unhealthy"]


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: ComponentName
    status: ComponentStatus
    message: str


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    ready: bool
    components: tuple[ComponentHealth, ...]


class HealthService:
    """Probe infrastructure independently and return redacted component status."""

    def __init__(self, sqlite_engine: Engine, duckdb_store: DuckDbStore) -> None:
        self._sqlite_engine = sqlite_engine
        self._duckdb_store = duckdb_store

    def readiness(self) -> ReadinessResult:
        components = (
            self._probe_sqlite(),
            self._probe_duckdb(),
        )
        return ReadinessResult(
            ready=all(component.status == "healthy" for component in components),
            components=components,
        )

    def _probe_sqlite(self) -> ComponentHealth:
        try:
            healthy = probe_sqlite(self._sqlite_engine)
        except Exception:
            logger.warning("SQLite dependency check failed", extra={"event": "health.sqlite"})
            return ComponentHealth("sqlite", "unhealthy", "dependency check failed")
        status: ComponentStatus = "healthy" if healthy else "unhealthy"
        message = "connection available" if healthy else "dependency check failed"
        return ComponentHealth("sqlite", status, message)

    def _probe_duckdb(self) -> ComponentHealth:
        try:
            healthy = self._duckdb_store.probe()
        except Exception:
            logger.warning("DuckDB dependency check failed", extra={"event": "health.duckdb"})
            return ComponentHealth("duckdb", "unhealthy", "dependency check failed")
        status: ComponentStatus = "healthy" if healthy else "unhealthy"
        message = "connection available" if healthy else "dependency check failed"
        return ComponentHealth("duckdb", status, message)
