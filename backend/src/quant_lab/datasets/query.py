from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import duckdb

from quant_lab.datasets.domain import DatasetVersionStatus
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.repository import DatasetRepository


class DatasetQueryService:
    def __init__(self, repository: DatasetRepository, published_root: Path) -> None:
        self.repository = repository
        self.published_root = published_root.resolve()

    def _files(self, dataset_id: str, version_id: str):
        version = self.repository.get_version(dataset_id, version_id)
        if version.status != DatasetVersionStatus.PUBLISHED.value:
            raise DatasetError("DATASET_VERSION_NOT_PUBLISHED", "仅可查询已发布版本")
        files = self.repository.list_files(version_id)
        if not files:
            raise DatasetError("PUBLISHED_DATASET_INCONSISTENT", "已发布版本文件缺失")
        paths: list[Path] = []
        for item in files:
            relative = Path(item.relative_path)
            path = (self.published_root / version.relative_version_root / relative).resolve()
            if self.published_root not in path.parents or not path.is_file():
                raise DatasetError("PUBLISHED_DATASET_INCONSISTENT", "已发布版本文件缺失")
            if path.stat().st_size != item.size_bytes:
                raise DatasetError("PUBLISHED_DATASET_INCONSISTENT", "已发布版本文件校验失败")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != item.sha256:
                raise DatasetError("PUBLISHED_DATASET_INCONSISTENT", "已发布版本文件校验失败")
            paths.append(path)
        return version, paths

    def summary(self, dataset_id: str, version_id: str) -> dict[str, object]:
        version, paths = self._files(dataset_id, version_id)
        return {
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "version": version.version,
            "row_count": version.row_count,
            "instrument_count": version.instrument_count,
            "min_timestamp": version.min_timestamp,
            "max_timestamp": version.max_timestamp,
            "file_count": len(paths),
            "manifest_sha256": version.manifest_sha256,
            "schema_version": version.schema_version,
            "normalization_version": version.normalization_version,
            "quality_rules_version": version.quality_rules_version,
            "quality_summary": version.quality_summary_json,
        }

    def bars(
        self,
        dataset_id: str,
        version_id: str,
        *,
        instrument_id: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        if limit < 1 or limit > 1000 or offset < 0:
            raise DatasetError("INVALID_QUERY_LIMIT", "查询范围无效")
        _, paths = self._files(dataset_id, version_id)
        connection = duckdb.connect(":memory:")
        try:
            relations = " UNION ALL ".join("SELECT * FROM read_parquet(?)" for _ in paths)
            predicates = []
            params: list[object] = [str(path) for path in paths]
            if instrument_id is not None:
                if len(instrument_id) > 64 or any(
                    ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
                    for ch in instrument_id
                ):
                    raise DatasetError("INVALID_INSTRUMENT_ID", "标的代码格式无效")
                predicates.append("instrument_id = ?")
                params.append(instrument_id)
            if start is not None:
                predicates.append("trade_date >= ?")
                params.append(start)
            if end is not None:
                predicates.append("trade_date <= ?")
                params.append(end)
            where = " WHERE " + " AND ".join(predicates) if predicates else ""
            sql = (
                "SELECT instrument_id,symbol,exchange,frequency,timestamp,trade_date,"
                "open,high,low,close,volume,amount,adjustment_type,quality_status,"
                f"source_batch_id FROM ({relations}){where} "
                "ORDER BY instrument_id,timestamp LIMIT ? OFFSET ?"
            )
            params.extend([limit, offset])
            result = connection.execute(sql, params)
            columns = [item[0] for item in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        finally:
            connection.close()
