from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True, slots=True)
class DuckDbStore:
    """Open short-lived DuckDB connections for local analytical operations."""

    path: Path

    def probe(self) -> bool:
        """Raise on failure and return true after a successful local query."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self.path))
        try:
            result = connection.execute("SELECT 1").fetchone()
            return result == (1,)
        finally:
            connection.close()
