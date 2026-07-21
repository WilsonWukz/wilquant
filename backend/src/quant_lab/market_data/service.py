from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_lab.market_data.domain import (
    MARKET_BAR_FIELD_MAPPING_WHITELIST,
    REQUIRED_MARKET_BAR_FIELDS,
    Bar,
    PreviewRecord,
    QualityStatus,
)
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.fingerprints import canonical_json_bytes
from quant_lab.market_data.processing import process_market_data
from quant_lab.market_data.providers import (
    DataSourceInput,
    LocalCsvMarketDataProvider,
    LocalParquetMarketDataProvider,
    MarketDataProvider,
    SourceInspection,
)
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.staging import StagedUpload
from quant_lab.market_data.versions import (
    NORMALIZATION_RULES_VERSION,
    PREVIEW_FINGERPRINT_VERSION,
    QUALITY_RULES_VERSION,
    SCHEMA_VERSION,
)


@dataclass(frozen=True, slots=True)
class InspectionResult:
    batch_id: str
    inspection: SourceInspection
    file_size: int


@dataclass(frozen=True, slots=True)
class PreviewResult:
    batch_id: str
    status: str
    row_count: int
    accepted_count: int
    rejected_count: int
    warning_count: int
    sample_rows: tuple[dict[str, str], ...]


class MarketDataImportService:
    def __init__(
        self,
        repository: MarketDataRepository,
        import_directory: Path,
        preview_rows: int,
    ) -> None:
        self._repository = repository
        self._import_directory = import_directory.resolve()
        self._preview_rows = preview_rows

    def inspect(self, upload: StagedUpload) -> InspectionResult:
        provider = self._provider_for(upload.path)
        source = DataSourceInput(upload.path, upload.original_filename, upload.sha256)
        inspection = provider.inspect(source)
        batch = self._repository.create_inspection(upload, inspection)
        return InspectionResult(batch.batch_id, inspection, upload.size)

    def preview(self, batch_id: str, field_mapping: dict[str, str]) -> PreviewResult:
        missing = REQUIRED_MARKET_BAR_FIELDS - field_mapping.keys()
        unsupported = field_mapping.keys() - MARKET_BAR_FIELD_MAPPING_WHITELIST
        if missing or unsupported:
            raise ImportDataError(
                "FIELD_MAPPING_ERROR", "字段映射缺少必填字段或包含不支持字段"
            )
        batch = self._repository.get_batch(batch_id)
        source_path = (self._import_directory / batch.source_file).resolve()
        if source_path.parent != self._import_directory:
            raise ImportDataError("INVALID_SOURCE", "导入来源无效")
        provider = self._provider_for(source_path)
        source_file_size = source_path.stat().st_size
        processed = process_market_data(
            provider=provider,
            source=DataSourceInput(source_path, batch.source_name, batch.source_file_hash),
            source_size=source_file_size,
            field_mapping=field_mapping,
            data_source=batch.provider_name,
            source_batch_id=batch_id,
        )
        updated = self._repository.complete_preview(
            batch_id,
            PreviewRecord(
                source_file_size=source_file_size,
                field_mapping_json=canonical_json_bytes(field_mapping).decode("utf-8"),
                provider_version=provider.version,
                schema_version=SCHEMA_VERSION,
                normalization_version=NORMALIZATION_RULES_VERSION,
                quality_rules_version=QUALITY_RULES_VERSION,
                preview_fingerprint_version=PREVIEW_FINGERPRINT_VERSION,
                row_count=processed.row_count,
                accepted_count=processed.accepted_count,
                rejected_count=processed.rejected_count,
                warning_count=processed.warning_count,
                preview_fingerprint=processed.preview_fingerprint,
                preview_completed_at=datetime.now(UTC),
                issues=processed.issues,
            ),
        )
        samples = tuple(
            self._serialize_bar(row.bar)
            for row in processed.rows
            if row.bar is not None and row.quality_status is not QualityStatus.REJECTED
        )[: self._preview_rows]
        return PreviewResult(
            batch_id,
            updated.status,
            updated.row_count,
            updated.accepted_count,
            updated.rejected_count,
            updated.warning_count,
            samples,
        )

    @staticmethod
    def _provider_for(path: Path) -> MarketDataProvider:
        if path.suffix.lower() == ".csv":
            return LocalCsvMarketDataProvider()
        if path.suffix.lower() == ".parquet":
            return LocalParquetMarketDataProvider()
        raise ImportDataError("UNSUPPORTED_FORMAT", "仅支持 CSV 或 Parquet 文件")

    @staticmethod
    def _serialize_bar(bar: Bar) -> dict[str, str]:
        return {
            "instrument_id": bar.instrument_id,
            "trade_date": bar.trade_date.isoformat(),
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "amount": str(bar.amount),
            "quality_status": bar.quality_status.value,
        }
