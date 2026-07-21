from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_lab.market_data.domain import ImportBatchStatus, PreviewRecord
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.fingerprints import canonical_json_bytes, fingerprint_issue
from quant_lab.market_data.persistence import (
    DataQualityIssueModel,
    DataSourceModel,
    ImportBatchModel,
)
from quant_lab.market_data.providers import SourceInspection
from quant_lab.market_data.staging import StagedUpload
from quant_lab.market_data.versions import ISSUE_FINGERPRINT_VERSION


class MarketDataRepository:
    # FAILED/STALE restart normalization; PUBLISH_FAILED must retry publication/recovery.
    _PREVIEWABLE_STATUSES = frozenset(
        {
            ImportBatchStatus.PENDING.value,
            ImportBatchStatus.PREVIEW_READY.value,
            ImportBatchStatus.FAILED.value,
            ImportBatchStatus.STALE.value,
        }
    )

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_inspection(
        self,
        upload: StagedUpload,
        inspection: SourceInspection,
    ) -> ImportBatchModel:
        now = datetime.now(UTC)
        with Session(self._engine) as session:
            duplicate = session.scalar(
                select(ImportBatchModel).where(
                    ImportBatchModel.source_file_hash == upload.sha256
                )
            )
            if duplicate is not None:
                raise ImportDataError("DUPLICATE_SOURCE", "相同内容的文件已经导入检查")
            source = DataSourceModel(
                source_id=str(uuid4()),
                identifier=inspection.provider_name,
                name=upload.original_filename,
                source_type=inspection.provider_name.upper(),
                is_local=True,
                version="1",
                original_file=upload.original_filename,
                created_at=now,
            )
            batch = ImportBatchModel(
                batch_id=str(uuid4()),
                data_source_id=source.source_id,
                provider_name=inspection.provider_name,
                source_name=upload.original_filename,
                source_file=upload.storage_key,
                source_file_hash=upload.sha256,
                requested_at=now,
                status=ImportBatchStatus.PENDING.value,
                row_count=inspection.row_count,
                accepted_count=0,
                rejected_count=0,
                warning_count=0,
                schema_version="1",
            )
            session.add_all([source, batch])
            try:
                session.commit()
            except IntegrityError as exc:
                raise ImportDataError("DUPLICATE_SOURCE", "相同内容的文件已经导入检查") from exc
            session.refresh(batch)
            session.expunge(batch)
            return batch

    def get_batch(self, batch_id: str) -> ImportBatchModel:
        with Session(self._engine) as session:
            batch = session.get(ImportBatchModel, batch_id)
            if batch is None:
                raise ImportDataError("BATCH_NOT_FOUND", "导入批次不存在")
            self._restore_preview_utc(batch)
            session.expunge(batch)
            return batch

    def complete_preview(
        self,
        batch_id: str,
        preview: PreviewRecord,
    ) -> ImportBatchModel:
        preview.validate()
        preview_completed_at = preview.preview_completed_at
        canonical_issues = {
            fingerprint_issue(issue): issue
            for issue in preview.issues
        }
        with Session(self._engine) as session:
            updated_batch_id = session.scalar(
                update(ImportBatchModel)
                .where(
                    ImportBatchModel.batch_id == batch_id,
                    ImportBatchModel.status.in_(self._PREVIEWABLE_STATUSES),
                )
                .values(
                    status=ImportBatchStatus.PREVIEW_READY.value,
                    started_at=func.coalesce(
                        ImportBatchModel.started_at, preview_completed_at
                    ),
                    completed_at=preview_completed_at,
                    row_count=preview.row_count,
                    accepted_count=preview.accepted_count,
                    rejected_count=preview.rejected_count,
                    warning_count=preview.warning_count,
                    source_file_size=preview.source_file_size,
                    field_mapping_json=preview.field_mapping_json,
                    provider_version=preview.provider_version,
                    schema_version=preview.schema_version,
                    normalization_version=preview.normalization_version,
                    quality_rules_version=preview.quality_rules_version,
                    preview_fingerprint_version=preview.preview_fingerprint_version,
                    preview_fingerprint=preview.preview_fingerprint,
                    preview_completed_at=preview_completed_at,
                )
                .returning(ImportBatchModel.batch_id)
            )
            if updated_batch_id is None:
                exists = session.scalar(
                    select(ImportBatchModel.batch_id).where(
                        ImportBatchModel.batch_id == batch_id
                    )
                )
                if exists is None:
                    raise ImportDataError("BATCH_NOT_FOUND", "导入批次不存在")
                raise ImportDataError(
                    "PREVIEW_STATE_INVALID", "当前批次状态不允许预览"
                )
            session.execute(
                delete(DataQualityIssueModel).where(
                    DataQualityIssueModel.batch_id == batch_id
                )
            )
            session.add_all(
                DataQualityIssueModel(
                    issue_id=str(uuid4()),
                    batch_id=batch_id,
                    row_number=issue.row_number,
                    symbol=issue.symbol,
                    field_name=issue.field_name,
                    severity=issue.severity.value,
                    issue_code=issue.issue_code,
                    message=issue.message,
                    raw_value=issue.raw_value,
                    issue_fingerprint=fingerprint,
                    issue_fingerprint_version=ISSUE_FINGERPRINT_VERSION,
                    normalized_value=(
                        None
                        if issue.normalized_value is None
                        else canonical_json_bytes(issue.normalized_value).decode("utf-8")
                    ),
                    created_at=preview_completed_at,
                )
                for fingerprint, issue in sorted(canonical_issues.items())
            )
            session.commit()
            batch = session.get(ImportBatchModel, batch_id)
            assert batch is not None
            self._restore_preview_utc(batch)
            session.expunge(batch)
            return batch

    def list_issues(self, batch_id: str) -> tuple[DataQualityIssueModel, ...]:
        self.get_batch(batch_id)
        with Session(self._engine) as session:
            items = tuple(
                session.scalars(
                    select(DataQualityIssueModel)
                    .where(DataQualityIssueModel.batch_id == batch_id)
                    .order_by(
                        DataQualityIssueModel.row_number,
                        DataQualityIssueModel.issue_code,
                        DataQualityIssueModel.field_name,
                        DataQualityIssueModel.issue_fingerprint,
                    )
                )
            )
            for item in items:
                session.expunge(item)
            return items

    @staticmethod
    def _restore_preview_utc(batch: ImportBatchModel) -> None:
        """SQLite returns naive datetimes; persisted Preview times are defined as UTC."""
        completed_at = batch.preview_completed_at
        if completed_at is not None and completed_at.tzinfo is None:
            batch.preview_completed_at = completed_at.replace(tzinfo=UTC)
