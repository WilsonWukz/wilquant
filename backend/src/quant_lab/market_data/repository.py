from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_lab.market_data.domain import ImportBatchStatus, QualityIssue
from quant_lab.market_data.errors import ImportDataError
from quant_lab.market_data.persistence import (
    DataQualityIssueModel,
    DataSourceModel,
    ImportBatchModel,
)
from quant_lab.market_data.providers import SourceInspection
from quant_lab.market_data.staging import StagedUpload


class MarketDataRepository:
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
            session.expunge(batch)
            return batch

    def complete_preview(
        self,
        batch_id: str,
        *,
        row_count: int,
        accepted_count: int,
        rejected_count: int,
        warning_count: int,
        issues: tuple[QualityIssue, ...],
    ) -> ImportBatchModel:
        now = datetime.now(UTC)
        canonical_issues = {
            self._issue_fingerprint(issue): issue
            for issue in issues
        }
        with Session(self._engine) as session:
            batch = session.get(ImportBatchModel, batch_id)
            if batch is None:
                raise ImportDataError("BATCH_NOT_FOUND", "导入批次不存在")
            batch.status = ImportBatchStatus.PREVIEW_READY.value
            batch.started_at = batch.started_at or now
            batch.completed_at = now
            batch.row_count = row_count
            batch.accepted_count = accepted_count
            batch.rejected_count = rejected_count
            batch.warning_count = warning_count
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
                    created_at=now,
                )
                for fingerprint, issue in sorted(canonical_issues.items())
            )
            session.commit()
            session.refresh(batch)
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
    def _issue_fingerprint(issue: QualityIssue) -> str:
        payload = json.dumps(
            [
                issue.row_number,
                issue.symbol,
                issue.field_name,
                issue.severity.value,
                issue.issue_code,
                issue.message,
                issue.raw_value,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
