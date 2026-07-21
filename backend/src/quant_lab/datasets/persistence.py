from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from quant_lab.db.sqlite import Base


class DatasetModel(Base):
    __tablename__ = "datasets"
    __table_args__ = (Index("ix_datasets_is_active", "is_active"),)

    dataset_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    logical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dataset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class DatasetVersionModel(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_versions_dataset_version"),
        UniqueConstraint(
            "publication_fingerprint",
            name="uq_dataset_versions_publication_fingerprint",
        ),
        Index("ix_dataset_versions_dataset_status", "dataset_id", "status"),
        Index("ix_dataset_versions_source_batch_id", "source_batch_id"),
    )

    dataset_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_batch_id: Mapped[str] = mapped_column(
        ForeignKey("import_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    source_preview_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_rules_version: Mapped[str] = mapped_column(String(64), nullable=False)
    publication_format_version: Mapped[str] = mapped_column(String(64), nullable=False)
    partition_strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    partition_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocking_issue_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_summary_json: Mapped[str | None] = mapped_column(Text)
    relative_version_root: Mapped[str | None] = mapped_column(String(1024))
    manifest_path: Mapped[str | None] = mapped_column(String(1024))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    publication_claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(Text)


class DatasetFileModel(Base):
    __tablename__ = "dataset_files"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "relative_path",
            name="uq_dataset_files_version_path",
        ),
        Index("ix_dataset_files_dataset_version_id", "dataset_version_id"),
    )

    dataset_file_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_version_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    partition_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    min_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationAuditModel(Base):
    __tablename__ = "publication_audits"
    __table_args__ = (
        Index("ix_publication_audits_batch_created_at", "batch_id", "created_at"),
    )

    publication_audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_label: Mapped[str | None] = mapped_column(String(255))
    request_note: Mapped[str | None] = mapped_column(Text)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("import_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.dataset_id", ondelete="RESTRICT"), nullable=False
    )
    dataset_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_versions.dataset_version_id", ondelete="RESTRICT")
    )
    expected_preview_fingerprint: Mapped[str | None] = mapped_column(String(64))
    actual_preview_fingerprint: Mapped[str | None] = mapped_column(String(64))
    publication_fingerprint: Mapped[str | None] = mapped_column(String(64))
    publication_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    confirm_warnings: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotent_replay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
