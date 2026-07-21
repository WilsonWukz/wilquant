from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_lab.core.config import RunMode
from quant_lab.datasets.domain import DatasetVersionStatus
from quant_lab.datasets.errors import DatasetError
from quant_lab.datasets.persistence import (
    DatasetModel,
    DatasetVersionModel,
    PublicationAuditModel,
)
from quant_lab.market_data.domain import ImportBatchStatus
from quant_lab.market_data.fingerprints import canonical_json_bytes
from quant_lab.market_data.persistence import DataQualityIssueModel, ImportBatchModel

_LOGICAL_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,254}$")
_IDENTITY_FIELDS = (
    "logical_key",
    "dataset_type",
    "market",
    "frequency",
    "adjustment_type",
    "schema_version",
)


@dataclass(frozen=True, slots=True)
class DatasetIdentity:
    logical_key: str
    dataset_type: str
    market: str
    frequency: str
    adjustment_type: str
    schema_version: str


@dataclass(frozen=True, slots=True)
class DatasetCreateResult:
    dataset: DatasetModel
    created: bool


@dataclass(frozen=True, slots=True)
class PublicationConfig:
    frequency: str
    adjustment_type: str
    schema_version: str
    publication_format_version: str
    partition_strategy_version: str
    compression_version: str
    column_definition_version: str


@dataclass(frozen=True, slots=True)
class PublicationClaimResult:
    version: DatasetVersionModel
    created: bool
    idempotent_replay: bool


def publication_fingerprint_for(
    *,
    source_preview_fingerprint: str,
    dataset_id: str,
    frequency: str,
    adjustment_type: str,
    schema_version: str,
    publication_format_version: str,
    partition_strategy_version: str,
    compression_version: str,
    column_definition_version: str,
) -> str:
    payload = {
        "version": "publication-sha256@1",
        "source_preview_fingerprint": source_preview_fingerprint,
        "dataset_id": dataset_id,
        "frequency": frequency,
        "adjustment_type": adjustment_type,
        "schema_version": schema_version,
        "publication_format_version": publication_format_version,
        "partition_strategy_version": partition_strategy_version,
        "compression_version": compression_version,
        "column_definition_version": column_definition_version,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _normalized_text(value: str, *, uppercase: bool = False) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    return normalized.upper() if uppercase else normalized


def canonical_dataset_identity(identity: DatasetIdentity) -> dict[str, str]:
    logical_key = _normalized_text(identity.logical_key).lower()
    if not _LOGICAL_KEY_PATTERN.fullmatch(logical_key):
        raise DatasetError("INVALID_DATASET_IDENTITY", "数据集逻辑标识无效")

    canonical = {
        "logical_key": logical_key,
        "dataset_type": _normalized_text(identity.dataset_type, uppercase=True),
        "market": _normalized_text(identity.market, uppercase=True),
        "frequency": _normalized_text(identity.frequency, uppercase=True),
        "adjustment_type": _normalized_text(identity.adjustment_type, uppercase=True),
        "schema_version": _normalized_text(identity.schema_version),
    }
    if any(not canonical[field] for field in _IDENTITY_FIELDS):
        raise DatasetError("INVALID_DATASET_IDENTITY", "数据集身份字段不能为空")
    return canonical


def dataset_key_for(identity: DatasetIdentity) -> str:
    payload = json.dumps(
        canonical_dataset_identity(identity),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _claim_time_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise DatasetError(
            "PUBLICATION_CLAIM_TIME_INVALID",
            "发布时间必须包含时区",
        )
    return value.astimezone(UTC)


def _restore_dataset_datetimes(dataset: DatasetModel) -> DatasetModel:
    dataset.created_at = cast(datetime, _utc_aware(dataset.created_at))
    dataset.updated_at = cast(datetime, _utc_aware(dataset.updated_at))
    return dataset


def _restore_version_datetimes(version: DatasetVersionModel) -> DatasetVersionModel:
    version.min_timestamp = _utc_aware(version.min_timestamp)
    version.max_timestamp = _utc_aware(version.max_timestamp)
    version.publication_claimed_at = cast(
        datetime,
        _utc_aware(version.publication_claimed_at),
    )
    version.published_at = _utc_aware(version.published_at)
    version.created_at = cast(datetime, _utc_aware(version.created_at))
    return version


class DatasetRepository:
    def __init__(self, engine: Engine, *, run_mode: RunMode | str) -> None:
        self._engine = engine
        self._run_mode = run_mode

    def create_or_get(
        self,
        identity: DatasetIdentity,
        *,
        name: str,
        description: str | None = None,
    ) -> DatasetCreateResult:
        canonical = canonical_dataset_identity(identity)
        dataset_key = dataset_key_for(identity)
        display_name = unicodedata.normalize("NFC", name).strip()
        if not display_name:
            raise DatasetError("INVALID_DATASET", "数据集名称不能为空")
        display_description = (
            unicodedata.normalize("NFC", description).strip() if description is not None else None
        )
        now = datetime.now(UTC)
        values = {
            "dataset_id": str(uuid4()),
            "dataset_key": dataset_key,
            **canonical,
            "name": display_name,
            "description": display_description or None,
            "created_at": now,
            "updated_at": now,
            "is_active": True,
        }
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            result = session.execute(
                sqlite_insert(DatasetModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[DatasetModel.dataset_key])
            )
            dataset = session.scalars(
                select(DatasetModel).where(DatasetModel.dataset_key == dataset_key)
            ).one()
            if any(getattr(dataset, field) != canonical[field] for field in _IDENTITY_FIELDS):
                raise DatasetError(
                    "DATASET_IDENTITY_CONFLICT",
                    "数据集身份冲突, 请检查本地数据一致性",
                )
            created = cast(CursorResult[Any], result).rowcount == 1
            _restore_dataset_datetimes(dataset)
            session.expunge(dataset)
        return DatasetCreateResult(dataset=dataset, created=created)

    def list_datasets(self) -> tuple[DatasetModel, ...]:
        with Session(self._engine) as session:
            datasets = tuple(
                _restore_dataset_datetimes(dataset)
                for dataset in session.scalars(
                    select(DatasetModel).order_by(
                        DatasetModel.created_at,
                        DatasetModel.dataset_id,
                    )
                )
            )
            session.expunge_all()
        return datasets

    def list_versions(self, dataset_id: str) -> tuple[DatasetVersionModel, ...]:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            versions = tuple(
                _restore_version_datetimes(version)
                for version in session.scalars(
                    select(DatasetVersionModel)
                    .where(DatasetVersionModel.dataset_id == dataset_id)
                    .order_by(DatasetVersionModel.version)
                )
            )
            session.expunge_all()
        return versions

    def get_version(self, dataset_id: str, version_id: str) -> DatasetVersionModel:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            version = session.scalar(
                select(DatasetVersionModel).where(
                    DatasetVersionModel.dataset_id == dataset_id,
                    DatasetVersionModel.dataset_version_id == version_id,
                )
            )
            if version is None:
                raise DatasetError("DATASET_VERSION_NOT_FOUND", "数据集版本不存在")
            _restore_version_datetimes(version)
            session.expunge(version)
        return version

    def assert_identity_mutable(self, dataset_id: str) -> None:
        self._require_dataset(dataset_id)
        with Session(self._engine) as session:
            version_id = session.scalar(
                select(DatasetVersionModel.dataset_version_id)
                .where(DatasetVersionModel.dataset_id == dataset_id)
                .limit(1)
            )
        if version_id is not None:
            raise DatasetError("DATASET_IDENTITY_IMMUTABLE", "已有版本的数据集身份不可修改")

    def claim_publication(
        self,
        *,
        batch_id: str,
        dataset_id: str,
        expected_preview_fingerprint: str,
        publication_config: PublicationConfig,
        confirm_warnings: bool,
        request_id: str,
        operator_label: str | None = None,
        request_note: str | None = None,
        claimed_at: datetime | None = None,
    ) -> PublicationClaimResult:
        if self._run_mode is not RunMode.RESEARCH:
            raise DatasetError(
                "PUBLICATION_DISABLED_FOR_RUN_MODE",
                "当前运行模式不允许发布数据集",
            )
        claim_time = _claim_time_utc(claimed_at)
        fingerprint: str | None = None
        connection = self._engine.connect()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            session = Session(bind=connection, expire_on_commit=False)
            try:
                dataset = session.get(DatasetModel, dataset_id)
                if dataset is None or not dataset.is_active:
                    raise DatasetError("DATASET_NOT_FOUND", "数据集不存在")
                batch = session.get(ImportBatchModel, batch_id)
                if batch is None:
                    raise DatasetError("BATCH_NOT_FOUND", "导入批次不存在")

                self._validate_persisted_preview(
                    batch,
                    expected_preview_fingerprint=expected_preview_fingerprint,
                )
                self._validate_publication_identity(
                    dataset,
                    batch,
                    publication_config=publication_config,
                )
                is_new_claim = batch.status == ImportBatchStatus.PREVIEW_READY.value
                if is_new_claim:
                    self._validate_preview_ready_eligibility(
                        session,
                        batch=batch,
                        confirm_warnings=confirm_warnings,
                    )
                elif batch.status not in {
                    ImportBatchStatus.PUBLISHING.value,
                    ImportBatchStatus.PUBLISHED.value,
                    ImportBatchStatus.PUBLISH_FAILED.value,
                }:
                    raise DatasetError(
                        "PUBLICATION_BATCH_NOT_READY",
                        "当前批次不可发布",
                    )

                fingerprint = publication_fingerprint_for(
                    source_preview_fingerprint=expected_preview_fingerprint,
                    dataset_id=dataset_id,
                    frequency=publication_config.frequency,
                    adjustment_type=publication_config.adjustment_type,
                    schema_version=publication_config.schema_version,
                    publication_format_version=publication_config.publication_format_version,
                    partition_strategy_version=publication_config.partition_strategy_version,
                    compression_version=publication_config.compression_version,
                    column_definition_version=publication_config.column_definition_version,
                )
                existing = session.scalar(
                    select(DatasetVersionModel).where(
                        DatasetVersionModel.publication_fingerprint == fingerprint
                    )
                )
                if existing is not None:
                    if existing.source_batch_id != batch_id:
                        raise DatasetError(
                            "PUBLICATION_FINGERPRINT_BATCH_CONFLICT",
                            "发布指纹已属于其他导入批次",
                        )
                    _restore_version_datetimes(existing)
                    session.expunge(existing)
                    connection.commit()
                    return PublicationClaimResult(
                        version=existing,
                        created=False,
                        idempotent_replay=True,
                    )
                if not is_new_claim:
                    raise DatasetError(
                        "PUBLICATION_REPLAY_MISMATCH",
                        "发布重试与原声明不一致",
                    )
                next_version = (
                    session.scalar(
                        select(func.max(DatasetVersionModel.version)).where(
                            DatasetVersionModel.dataset_id == dataset_id
                        )
                    )
                    or 0
                ) + 1
                version = DatasetVersionModel(
                    dataset_version_id=str(uuid4()),
                    dataset_id=dataset_id,
                    version=next_version,
                    status=DatasetVersionStatus.VALIDATING.value,
                    source_batch_id=batch_id,
                    source_preview_fingerprint=expected_preview_fingerprint,
                    publication_fingerprint=fingerprint,
                    schema_version=publication_config.schema_version,
                    normalization_version=cast(str, batch.normalization_version),
                    quality_rules_version=cast(str, batch.quality_rules_version),
                    publication_format_version=publication_config.publication_format_version,
                    partition_strategy_version=publication_config.partition_strategy_version,
                    row_count=0,
                    instrument_count=0,
                    partition_count=0,
                    file_count=0,
                    total_size_bytes=0,
                    quality_issue_count=0,
                    warning_count=batch.warning_count,
                    blocking_issue_count=0,
                    publication_claimed_at=claim_time,
                    created_at=claim_time,
                )
                session.add(version)
                session.flush()
                batch.status = ImportBatchStatus.PUBLISHING.value
                session.add(
                    PublicationAuditModel(
                        publication_audit_id=str(uuid4()),
                        request_id=request_id,
                        actor_type="LOCAL_UNAUTHENTICATED_USER",
                        operator_label=operator_label,
                        request_note=request_note,
                        batch_id=batch_id,
                        dataset_id=dataset_id,
                        dataset_version_id=version.dataset_version_id,
                        expected_preview_fingerprint=expected_preview_fingerprint,
                        actual_preview_fingerprint=batch.preview_fingerprint,
                        publication_fingerprint=fingerprint,
                        publication_config_json=canonical_json_bytes(
                            {
                                "frequency": publication_config.frequency,
                                "adjustment_type": publication_config.adjustment_type,
                                "schema_version": publication_config.schema_version,
                                "publication_format_version": (
                                    publication_config.publication_format_version
                                ),
                                "partition_strategy_version": (
                                    publication_config.partition_strategy_version
                                ),
                                "compression_version": publication_config.compression_version,
                                "column_definition_version": (
                                    publication_config.column_definition_version
                                ),
                            }
                        ).decode("utf-8"),
                        confirm_warnings=confirm_warnings,
                        result="CLAIMED",
                        file_count=0,
                        row_count=0,
                        idempotent_replay=False,
                        created_at=claim_time,
                    )
                )
                session.flush()
                connection.commit()
                _restore_version_datetimes(version)
                session.expunge(version)
                return PublicationClaimResult(
                    version=version,
                    created=True,
                    idempotent_replay=False,
                )
            except IntegrityError as error:
                connection.rollback()
                if fingerprint is not None:
                    with Session(self._engine) as winner_session:
                        winner = winner_session.scalar(
                            select(DatasetVersionModel).where(
                                DatasetVersionModel.publication_fingerprint == fingerprint
                            )
                        )
                        if winner is not None:
                            if winner.source_batch_id != batch_id:
                                raise DatasetError(
                                    "PUBLICATION_FINGERPRINT_BATCH_CONFLICT",
                                    "发布指纹已属于其他导入批次",
                                ) from error
                            _restore_version_datetimes(winner)
                            winner_session.expunge(winner)
                            return PublicationClaimResult(
                                version=winner,
                                created=False,
                                idempotent_replay=True,
                            )
                raise DatasetError(
                    "PUBLICATION_CLAIM_CONFLICT",
                    "发布声明发生并发冲突, 请重试",
                ) from error
            except Exception:
                connection.rollback()
                raise
            finally:
                session.close()
        finally:
            connection.close()

    @staticmethod
    def _validate_persisted_preview(
        batch: ImportBatchModel,
        *,
        expected_preview_fingerprint: str,
    ) -> None:
        preview_fields = (
            batch.field_mapping_json,
            batch.provider_version,
            batch.normalization_version,
            batch.quality_rules_version,
            batch.preview_fingerprint_version,
            batch.preview_fingerprint,
            batch.preview_completed_at,
        )
        if any(value is None or value == "" for value in preview_fields):
            raise DatasetError(
                "PUBLICATION_PREVIEW_INCOMPLETE",
                "预览记录不完整, 请重新预览",
            )
        if batch.preview_fingerprint != expected_preview_fingerprint:
            raise DatasetError(
                "PREVIEW_FINGERPRINT_MISMATCH",
                "预览指纹不一致, 请重新预览",
            )

    @staticmethod
    def _validate_publication_identity(
        dataset: DatasetModel,
        batch: ImportBatchModel,
        *,
        publication_config: PublicationConfig,
    ) -> None:
        if (
            dataset.frequency != publication_config.frequency
            or dataset.adjustment_type != publication_config.adjustment_type
            or dataset.schema_version != publication_config.schema_version
            or batch.schema_version != publication_config.schema_version
        ):
            raise DatasetError(
                "PUBLICATION_DATASET_MISMATCH",
                "数据集身份与发布配置不一致",
            )

    @staticmethod
    def _validate_preview_ready_eligibility(
        session: Session,
        *,
        batch: ImportBatchModel,
        confirm_warnings: bool,
    ) -> None:
        if batch.status != ImportBatchStatus.PREVIEW_READY.value:
            raise DatasetError("PUBLICATION_BATCH_NOT_READY", "当前批次不可发布")
        if batch.accepted_count <= 0:
            raise DatasetError("PUBLICATION_PREVIEW_EMPTY", "没有可发布的数据")
        blocking_issues = session.scalar(
            select(func.count())
            .select_from(DataQualityIssueModel)
            .where(
                DataQualityIssueModel.batch_id == batch.batch_id,
                DataQualityIssueModel.severity.in_(("ERROR", "FATAL")),
            )
        )
        if batch.rejected_count > 0 or blocking_issues:
            raise DatasetError(
                "PUBLICATION_BLOCKED_BY_QUALITY",
                "预览存在阻断性质量问题",
            )
        if batch.warning_count > 0 and not confirm_warnings:
            raise DatasetError(
                "PUBLICATION_WARNINGS_NOT_CONFIRMED",
                "请先确认质量警告",
            )

    def _require_dataset(self, dataset_id: str) -> None:
        with Session(self._engine) as session:
            exists = session.scalar(
                select(DatasetModel.dataset_id).where(DatasetModel.dataset_id == dataset_id)
            )
        if exists is None:
            raise DatasetError("DATASET_NOT_FOUND", "数据集不存在")
