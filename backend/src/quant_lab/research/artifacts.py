from __future__ import annotations

import json
from pathlib import Path

import duckdb

from quant_lab.datasets.errors import DatasetError


class ArtifactIntegrityError(DatasetError):
    def __init__(self, safe_message: str) -> None:
        super().__init__("ARTIFACT_INTEGRITY_FAILURE", safe_message)


class ArtifactReader:
    """Read-only access to immutable backtest artifacts (Parquet row_json + JSON)."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root.resolve()

    def read_rows(self, artifact) -> list[dict[str, object]]:
        path = self.runtime_root / artifact.relative_path
        if not path.is_file():
            raise ArtifactIntegrityError("回测产物文件缺失")
        connection = duckdb.connect()
        try:
            result = connection.execute("SELECT row_json FROM read_parquet(?)", [str(path)])
            return [json.loads(row[0]) for row in result.fetchall()]
        except Exception as exc:
            raise ArtifactIntegrityError("回测产物无法解析") from exc
        finally:
            connection.close()

    def read_json(self, artifact) -> dict[str, object]:
        path = self.runtime_root / artifact.relative_path
        if not path.is_file():
            raise ArtifactIntegrityError("回测产物文件缺失")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ArtifactIntegrityError("回测产物无法解析") from exc
