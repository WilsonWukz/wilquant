from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb

from quant_lab.backtest.engine import BacktestResult
from quant_lab.backtest.metrics import calculate_metrics
from quant_lab.market_data.fingerprints import canonical_json_bytes


class ArtifactError(ValueError):
    pass


class BacktestArtifactWriter:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root.resolve()

    def write(
        self,
        *,
        run_id: str,
        result: BacktestResult,
        run_metadata: dict[str, object],
    ) -> tuple[str, list[dict[str, object]]]:
        staging_root = self.runtime_root / "backtests" / ".staging" / run_id
        final_root = self.runtime_root / "backtests" / run_id
        if final_root.exists():
            return self._existing_manifest(final_root)
        staging_root.mkdir(parents=True, exist_ok=False)
        try:
            metrics = calculate_metrics(result.equity_curve, result.orders, result.fills)
            artifacts: list[dict[str, object]] = []
            rows_by_type = {
                "ORDERS": [asdict(item) for item in result.orders],
                "FILLS": [asdict(item) for item in result.fills],
                "POSITIONS": [asdict(item) for item in result.positions],
                "EQUITY_CURVE": [asdict(item) for item in result.equity_curve],
            }
            for artifact_type, rows in rows_by_type.items():
                relative = f"backtests/{run_id}/{artifact_type.lower()}.parquet"
                path = staging_root / f"{artifact_type.lower()}.parquet"
                self._write_parquet(path, rows)
                artifacts.append(self._file_record(artifact_type, relative, path, len(rows)))
            metrics_path = staging_root / "metrics.json"
            metrics_path.write_bytes(canonical_json_bytes(metrics))
            artifacts.append(
                self._file_record("METRICS", f"backtests/{run_id}/metrics.json", metrics_path, 1)
            )
            manifest = {
                **run_metadata,
                "run_id": run_id,
                "relative_path": f"backtests/{run_id}/manifest.json",
                "artifacts": artifacts,
                "created_at": datetime.now(UTC),
            }
            manifest_path = staging_root / "manifest.json"
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            artifacts.append(
                self._file_record(
                    "MANIFEST", f"backtests/{run_id}/manifest.json", manifest_path, len(artifacts)
                )
            )
            final_root.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_root, final_root)
            return f"backtests/{run_id}/manifest.json", artifacts
        except Exception:
            shutil.rmtree(staging_root, ignore_errors=True)
            raise

    @staticmethod
    def _write_parquet(path: Path, rows: list[dict[str, object]]) -> None:
        connection = duckdb.connect()
        try:
            connection.execute("CREATE TABLE artifact (row_json VARCHAR)")
            for row in rows:
                connection.execute(
                    "INSERT INTO artifact VALUES (?)", [json.dumps(_jsonable(row), sort_keys=True)]
                )
            connection.execute("COPY artifact TO ? (FORMAT PARQUET)", [str(path)])
        finally:
            connection.close()

    @staticmethod
    def _file_record(
        artifact_type: str, relative: str, path: Path, row_count: int
    ) -> dict[str, object]:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "artifact_type": artifact_type,
            "relative_path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": digest,
            "row_count": row_count,
        }

    @staticmethod
    def _existing_manifest(final_root: Path):
        manifest = final_root / "manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return payload["relative_path"], payload["artifacts"]


def _jsonable(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
