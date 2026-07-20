from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quant_lab.market_data.domain import (
    Bar,
    IssueSeverity,
    QualityIssue,
    QualityStatus,
    ValidationResult,
)
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.normalization import normalize_daily_bar
from quant_lab.market_data.providers import (
    DataSourceInput,
    LocalCsvMarketDataProvider,
    LocalParquetMarketDataProvider,
    MarketDataProvider,
    SourceInspection,
)
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.staging import StagedUpload
from quant_lab.market_data.validation import validate_bars

REQUIRED_FIELDS = {
    "symbol",
    "exchange",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
}


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
        missing = REQUIRED_FIELDS - field_mapping.keys()
        if missing:
            raise ImportDataError("FIELD_MAPPING_ERROR", "缺少必填字段映射")
        batch = self._repository.get_batch(batch_id)
        source_path = (self._import_directory / batch.source_file).resolve()
        if source_path.parent != self._import_directory:
            raise ImportDataError("INVALID_SOURCE", "导入来源无效")
        provider = self._provider_for(source_path)
        raw_batch = provider.load_bars(
            DataSourceInput(source_path, batch.source_name, batch.source_file_hash)
        )
        parsed: list[tuple[int, Bar]] = []
        parse_issues: list[QualityIssue] = []
        for raw_row in raw_batch.rows:
            try:
                values = {field: raw_row.values[field_mapping[field]] for field in REQUIRED_FIELDS}
                parsed.append(
                    (
                        raw_row.row_number,
                        normalize_daily_bar(
                            symbol=values["symbol"],
                            exchange=values["exchange"],
                            trade_date=values["trade_date"],
                            open_value=values["open"],
                            high_value=values["high"],
                            low_value=values["low"],
                            close_value=values["close"],
                            volume_value=values["volume"],
                            amount_value=values["amount"],
                            data_source=batch.provider_name,
                            source_batch_id=batch_id,
                        ),
                    )
                )
            except (KeyError, ValueError) as exc:
                parse_issues.append(
                    QualityIssue(
                        raw_row.row_number,
                        raw_row.values.get(field_mapping.get("symbol", "")),
                        None,
                        IssueSeverity.ERROR,
                        "TYPE_PARSE_ERROR",
                        str(exc),
                    )
                )
        validation = (
            validate_bars(parsed)
            if parsed or not raw_batch.rows
            else ValidationResult((), ())
        )
        all_issues = tuple(parse_issues) + validation.issues
        rejected_count = len(parse_issues) + validation.rejected_count
        updated = self._repository.complete_preview(
            batch_id,
            row_count=len(raw_batch.rows),
            accepted_count=validation.accepted_count,
            rejected_count=rejected_count,
            warning_count=validation.warning_count,
            issues=all_issues,
        )
        samples = tuple(
            self._serialize_bar(row.bar)
            for row in validation.rows
            if row.quality_status is not QualityStatus.REJECTED
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
