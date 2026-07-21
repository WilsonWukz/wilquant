from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from pathlib import Path

import duckdb

from quant_lab.core.config import Settings
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.repository import DatasetRepository, PublicationConfig
from quant_lab.market_data.domain import QualityStatus
from quant_lab.market_data.fingerprints import canonical_json_bytes, fingerprint_issue
from quant_lab.market_data.processing import process_market_data
from quant_lab.market_data.providers import (
    DataSourceInput,
    LocalCsvMarketDataProvider,
    LocalParquetMarketDataProvider,
)
from quant_lab.market_data.repository import MarketDataRepository
from quant_lab.market_data.versions import (
    NORMALIZATION_RULES_VERSION,
    QUALITY_RULES_VERSION,
    SCHEMA_VERSION,
)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class PublicationService:
    def __init__(
        self,
        repository: DatasetRepository,
        market_repository: MarketDataRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.market_repository = market_repository
        self.settings = settings

    def publish(
        self,
        *,
        dataset_id: str,
        batch_id: str,
        expected_preview_fingerprint: str,
        confirm_warnings: bool,
        request_id: str,
        frequency: str = "DAILY",
        adjustment_type: str = "NONE",
        operator_label: str | None = None,
        request_note: str | None = None,
    ):
        config = PublicationConfig(
            frequency,
            adjustment_type,
            SCHEMA_VERSION,
            "parquet@1",
            "frequency-exchange-year@1",
            "zstd@1",
            "market-bar-columns@1",
        )
        config_json = canonical_json_bytes(
            {
                "frequency": frequency,
                "adjustment_type": adjustment_type,
                "schema_version": SCHEMA_VERSION,
                "publication_format_version": "parquet@1",
                "partition_strategy_version": "frequency-exchange-year@1",
                "compression_version": "zstd@1",
                "column_definition_version": "market-bar-columns@1",
            }
        ).decode()
        batch = self.market_repository.get_batch(batch_id)
        if not batch.preview_fingerprint:
            raise DatasetError("PUBLICATION_PREVIEW_REQUIRED", "preview required")
        source = (self.settings.import_directory / batch.source_file).resolve()
        if source.parent != self.settings.import_directory.resolve() or not source.exists():
            raise DatasetError("SOURCE_FILE_NOT_FOUND", "source file unavailable")
        if (
            source.stat().st_size != batch.source_file_size
            or _sha(source) != batch.source_file_hash
        ):
            raise DatasetError("SOURCE_FILE_CHANGED", "source file changed; preview again")
        mapping = json.loads(batch.field_mapping_json or "{}")
        provider = (
            LocalParquetMarketDataProvider()
            if source.suffix.lower() == ".parquet"
            else LocalCsvMarketDataProvider()
        )
        processed = process_market_data(
            provider=provider,
            source=DataSourceInput(source, batch.source_name, batch.source_file_hash),
            source_size=source.stat().st_size,
            field_mapping=mapping,
            data_source=batch.provider_name,
            source_batch_id=batch_id,
            schema_version=SCHEMA_VERSION,
            normalization_version=NORMALIZATION_RULES_VERSION,
            quality_rules_version=QUALITY_RULES_VERSION,
        )
        if (
            processed.preview_fingerprint != expected_preview_fingerprint
            or processed.preview_fingerprint != batch.preview_fingerprint
            or (
                processed.row_count,
                processed.accepted_count,
                processed.rejected_count,
                processed.warning_count,
            )
            != (batch.row_count, batch.accepted_count, batch.rejected_count, batch.warning_count)
        ):
            raise DatasetError(
                "PREVIEW_FINGERPRINT_MISMATCH", "recomputed preview differs; preview again"
            )
        claim = self.repository.claim_publication(
            batch_id=batch_id,
            dataset_id=dataset_id,
            expected_preview_fingerprint=batch.preview_fingerprint,
            publication_config=config,
            confirm_warnings=confirm_warnings,
            request_id=request_id,
            operator_label=operator_label,
            request_note=request_note,
        )
        if claim.idempotent_replay and claim.version.status == "PUBLISHED":
            return claim.version
        version = claim.version
        staging = self.settings.publication_staging_directory / version.dataset_version_id
        relative_root = f"market_bars/dataset={dataset_id}/version={version.version:06d}"
        final = self.settings.published_directory / relative_root
        try:
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            rows = [
                r.bar
                for r in processed.rows
                if r.bar is not None and r.quality_status is not QualityStatus.REJECTED
            ]
            groups: dict[tuple[str, str, int], list] = defaultdict(list)
            for bar in sorted(
                rows,
                key=lambda b: (
                    b.frequency.value,
                    b.exchange.value,
                    b.instrument_id,
                    b.trade_date,
                    b.timestamp,
                ),
            ):
                groups[(bar.frequency.value, bar.exchange.value, bar.trade_date.year)].append(bar)
            if len(groups) > 64:
                raise DatasetError("PUBLICATION_TOO_MANY_PARTITIONS", "too many partitions")
            files = []
            con = duckdb.connect()
            try:
                con.execute(
                    "CREATE TABLE bars (instrument_id VARCHAR, symbol VARCHAR, exchange VARCHAR, "
                    "frequency VARCHAR, timestamp TIMESTAMP, trade_date DATE, "
                    "open DECIMAL(20,8), high DECIMAL(20,8), low DECIMAL(20,8), "
                    "close DECIMAL(20,8), volume BIGINT, amount DECIMAL(20,8), "
                    "adjustment_type VARCHAR, quality_status VARCHAR, source_batch_id VARCHAR)"
                )
                for ordinal, ((freq, exch, year), bars) in enumerate(groups.items()):
                    con.executemany(
                        "INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [
                            (
                                b.instrument_id,
                                b.symbol,
                                b.exchange.value,
                                b.frequency.value,
                                b.timestamp,
                                b.trade_date,
                                b.open,
                                b.high,
                                b.low,
                                b.close,
                                b.volume,
                                b.amount,
                                b.adjustment_type.value,
                                b.quality_status.value,
                                b.source_batch_id,
                            )
                            for b in bars
                        ],
                    )
                    part_dir = staging / f"frequency={freq}" / f"exchange={exch}" / f"year={year}"
                    part_dir.mkdir(parents=True, exist_ok=True)
                    tmp = part_dir / f"part-{ordinal:05d}.parquet.tmp"
                    rel = tmp.with_suffix("").relative_to(staging).as_posix()
                    con.execute(
                        "COPY (SELECT * FROM bars) TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
                        [str(tmp)],
                    )
                    con.execute("DELETE FROM bars")
                    os.replace(tmp, part_dir / Path(rel).name)
                    actual = part_dir / Path(rel).name
                    files.append(
                        {
                            "relative_path": actual.relative_to(staging).as_posix(),
                            "partition_values_json": canonical_json_bytes(
                                {"frequency": freq, "exchange": exch, "year": year}
                            ).decode(),
                            "row_count": len(bars),
                            "size_bytes": actual.stat().st_size,
                            "sha256": _sha(actual),
                            "min_timestamp": min(b.timestamp for b in bars),
                            "max_timestamp": max(b.timestamp for b in bars),
                        }
                    )
            finally:
                con.close()
            manifest_files = [
                dict(
                    item,
                    min_timestamp=item["min_timestamp"].isoformat(),
                    max_timestamp=item["max_timestamp"].isoformat(),
                )
                for item in files
            ]
            manifest = {
                "dataset_id": dataset_id,
                "dataset_version_id": version.dataset_version_id,
                "version": version.version,
                "import_batch_id": batch_id,
                "source_sha256": batch.source_file_hash,
                "provider": {"name": provider.name, "version": provider.version},
                "mapping": mapping,
                "schema_version": SCHEMA_VERSION,
                "normalization_version": NORMALIZATION_RULES_VERSION,
                "quality_rules_version": QUALITY_RULES_VERSION,
                "preview_fingerprint": processed.preview_fingerprint,
                "publication_fingerprint": version.publication_fingerprint,
                "issue_fingerprints": sorted(fingerprint_issue(i) for i in processed.issues),
                "row_count": processed.row_count,
                "accepted_count": processed.accepted_count,
                "rejected_count": processed.rejected_count,
                "warning_count": processed.warning_count,
                "files": manifest_files,
                "publication_claimed_at": version.publication_claimed_at.isoformat(),
            }
            manifest_bytes = canonical_json_bytes(manifest) + b"\n"
            manifest_tmp = staging / "manifest.json.tmp"
            manifest_tmp.write_bytes(manifest_bytes)
            manifest_path_local = staging / "manifest.json"
            os.replace(manifest_tmp, manifest_path_local)
            self.repository.mark_files_committing(version.dataset_version_id)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final)
            self.repository.mark_files_committed(version.dataset_version_id)
            return self.repository.finalize_publication(
                version_id=version.dataset_version_id,
                batch_id=batch_id,
                dataset_id=dataset_id,
                files=files,
                relative_root=relative_root,
                manifest_path=f"{relative_root}/manifest.json",
                manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                row_count=processed.row_count,
                instrument_count=len({b.instrument_id for b in rows}),
                min_timestamp=min((b.timestamp for b in rows), default=None),
                max_timestamp=max((b.timestamp for b in rows), default=None),
                partition_count=len(files),
                total_size_bytes=sum(int(f["size_bytes"]) for f in files),
                quality_issue_count=len(processed.issues),
                warning_count=processed.warning_count,
                blocking_issue_count=processed.rejected_count,
                quality_summary_json=canonical_json_bytes(
                    {
                        "accepted": processed.accepted_count,
                        "rejected": processed.rejected_count,
                        "warning": processed.warning_count,
                    }
                ).decode(),
                request_id=request_id,
                publication_fingerprint=version.publication_fingerprint,
                config_json=config_json,
                confirm_warnings=confirm_warnings,
                claimed_at=version.publication_claimed_at,
            )
        except DatasetError:
            self.repository.mark_publication_failed(
                version_id=version.dataset_version_id,
                batch_id=batch_id,
                code="PUBLICATION_FAILED",
                reason="publication failed",
                request_id=request_id,
                config_json=config_json,
                confirm_warnings=confirm_warnings,
            )
            raise
        except Exception as exc:
            self.repository.mark_publication_failed(
                version_id=version.dataset_version_id,
                batch_id=batch_id,
                code="PUBLICATION_FAILED",
                reason="publication failed",
                request_id=request_id,
                config_json=config_json,
                confirm_warnings=confirm_warnings,
            )
            raise DatasetError("PUBLICATION_FAILED", "publication failed") from exc
