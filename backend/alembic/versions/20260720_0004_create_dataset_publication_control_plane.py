"""Create the immutable dataset publication control plane."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0004"
down_revision: str | None = "20260720_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ISSUE_INDEX = "uq_data_quality_issues_batch_fingerprint"
_ISSUE_FINGERPRINT_VERSION = "quality-issue-sha256@2"
_TRIGGERS = (
    "trg_dataset_files_published_no_delete",
    "trg_dataset_files_published_no_update",
    "trg_dataset_versions_published_no_delete",
    "trg_dataset_versions_published_no_update",
)


def _canonical_text(value: str) -> str:
    normalized_lines = value.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalized_lines)


def _v2_fingerprint(row: Mapping[str, Any]) -> str:
    payload = {
        "canonical_normalized_value": None,
        "canonical_raw_value": (
            None if row["raw_value"] is None else _canonical_text(row["raw_value"])
        ),
        "field_name": None if row["field_name"] is None else _canonical_text(row["field_name"]),
        "instrument_id": None,
        "issue_code": _canonical_text(row["issue_code"]),
        "row_number": row["row_number"],
        "severity": _canonical_text(row["severity"]),
        "symbol": None if row["symbol"] is None else _canonical_text(row["symbol"]),
        "version": _ISSUE_FINGERPRINT_VERSION,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _v1_fingerprint(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        [
            row["row_number"],
            row["symbol"],
            row["field_name"],
            row["severity"],
            row["issue_code"],
            row["message"],
            row["raw_value"],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _issue_table(*, include_v2: bool) -> sa.TableClause:
    columns = [
        sa.column("issue_id", sa.String(36)),
        sa.column("batch_id", sa.String(36)),
        sa.column("row_number", sa.Integer()),
        sa.column("symbol", sa.String(16)),
        sa.column("field_name", sa.String(100)),
        sa.column("severity", sa.String(16)),
        sa.column("issue_code", sa.String(64)),
        sa.column("message", sa.Text()),
        sa.column("raw_value", sa.Text()),
        sa.column("issue_fingerprint", sa.String(64)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    ]
    if include_v2:
        columns.extend(
            [
                sa.column("issue_fingerprint_version", sa.String(64)),
                sa.column("normalized_value", sa.Text()),
            ]
        )
    return sa.table("data_quality_issues", *columns)


def _rebuild_issue_fingerprints(*, version: int) -> None:
    issues = _issue_table(include_v2=version == 2)
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(issues).order_by(issues.c.created_at, issues.c.issue_id)
    ).mappings()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        fingerprint = _v2_fingerprint(row) if version == 2 else _v1_fingerprint(row)
        identity = (row["batch_id"], fingerprint)
        if identity in seen:
            connection.execute(sa.delete(issues).where(issues.c.issue_id == row["issue_id"]))
            continue
        seen.add(identity)
        values = {"issue_fingerprint": fingerprint}
        if version == 2:
            values["issue_fingerprint_version"] = _ISSUE_FINGERPRINT_VERSION
        connection.execute(
            sa.update(issues).where(issues.c.issue_id == row["issue_id"]).values(**values)
        )


def _upgrade_issues() -> None:
    op.drop_index(_ISSUE_INDEX, table_name="data_quality_issues")
    op.add_column(
        "data_quality_issues",
        sa.Column("issue_fingerprint_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "data_quality_issues",
        sa.Column("normalized_value", sa.Text(), nullable=True),
    )
    _rebuild_issue_fingerprints(version=2)
    with op.batch_alter_table("data_quality_issues") as batch_op:
        batch_op.alter_column(
            "issue_fingerprint_version",
            existing_type=sa.String(64),
            nullable=False,
        )
    op.create_index(
        _ISSUE_INDEX,
        "data_quality_issues",
        ["batch_id", "issue_fingerprint"],
        unique=True,
    )


def _downgrade_issues() -> None:
    op.drop_index(_ISSUE_INDEX, table_name="data_quality_issues")
    _rebuild_issue_fingerprints(version=1)
    with op.batch_alter_table("data_quality_issues") as batch_op:
        batch_op.drop_column("normalized_value")
        batch_op.drop_column("issue_fingerprint_version")
    op.create_index(
        _ISSUE_INDEX,
        "data_quality_issues",
        ["batch_id", "issue_fingerprint"],
        unique=True,
    )


def _extend_import_batches() -> None:
    columns = (
        sa.Column("source_file_size", sa.Integer(), nullable=True),
        sa.Column("field_mapping_json", sa.Text(), nullable=True),
        sa.Column("provider_version", sa.String(64), nullable=True),
        sa.Column("normalization_version", sa.String(64), nullable=True),
        sa.Column("quality_rules_version", sa.String(64), nullable=True),
        sa.Column("preview_fingerprint_version", sa.String(64), nullable=True),
        sa.Column("preview_fingerprint", sa.String(64), nullable=True),
        sa.Column("preview_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("import_batches", column)


def _create_tables() -> None:
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("dataset_key", sa.String(64), nullable=False),
        sa.Column("logical_key", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("dataset_type", sa.String(32), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("adjustment_type", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id", name="pk_datasets"),
        sa.UniqueConstraint("dataset_key", name="uq_datasets_dataset_key"),
    )
    op.create_index("ix_datasets_is_active", "datasets", ["is_active"])

    op.create_table(
        "dataset_versions",
        sa.Column("dataset_version_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_batch_id", sa.String(36), nullable=False),
        sa.Column("source_preview_fingerprint", sa.String(64), nullable=False),
        sa.Column("publication_fingerprint", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("normalization_version", sa.String(64), nullable=False),
        sa.Column("quality_rules_version", sa.String(64), nullable=False),
        sa.Column("publication_format_version", sa.String(64), nullable=False),
        sa.Column("partition_strategy_version", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("instrument_count", sa.Integer(), nullable=False),
        sa.Column("min_timestamp", sa.DateTime(timezone=True)),
        sa.Column("max_timestamp", sa.DateTime(timezone=True)),
        sa.Column("partition_count", sa.Integer(), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("total_size_bytes", sa.Integer(), nullable=False),
        sa.Column("quality_issue_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("blocking_issue_count", sa.Integer(), nullable=False),
        sa.Column("quality_summary_json", sa.Text()),
        sa.Column("relative_version_root", sa.String(1024)),
        sa.Column("manifest_path", sa.String(1024)),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("publication_claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_reason", sa.Text()),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_dataset_versions_dataset_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_batch_id"],
            ["import_batches.batch_id"],
            name="fk_dataset_versions_source_batch_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("dataset_version_id", name="pk_dataset_versions"),
        sa.UniqueConstraint(
            "dataset_id", "version", name="uq_dataset_versions_dataset_version"
        ),
        sa.UniqueConstraint(
            "publication_fingerprint",
            name="uq_dataset_versions_publication_fingerprint",
        ),
    )
    op.create_index(
        "ix_dataset_versions_dataset_status", "dataset_versions", ["dataset_id", "status"]
    )
    op.create_index(
        "ix_dataset_versions_source_batch_id", "dataset_versions", ["source_batch_id"]
    )

    op.create_table(
        "dataset_files",
        sa.Column("dataset_file_id", sa.String(36), nullable=False),
        sa.Column("dataset_version_id", sa.String(36), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("partition_values_json", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("min_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.dataset_version_id"],
            name="fk_dataset_files_dataset_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("dataset_file_id", name="pk_dataset_files"),
        sa.UniqueConstraint(
            "dataset_version_id", "relative_path", name="uq_dataset_files_version_path"
        ),
    )
    op.create_index(
        "ix_dataset_files_dataset_version_id", "dataset_files", ["dataset_version_id"]
    )

    op.create_table(
        "publication_audits",
        sa.Column("publication_audit_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("actor_type", sa.String(64), nullable=False),
        sa.Column("operator_label", sa.String(255)),
        sa.Column("request_note", sa.Text()),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("dataset_id", sa.String(36), nullable=False),
        sa.Column("dataset_version_id", sa.String(36)),
        sa.Column("expected_preview_fingerprint", sa.String(64)),
        sa.Column("actual_preview_fingerprint", sa.String(64)),
        sa.Column("publication_fingerprint", sa.String(64)),
        sa.Column("publication_config_json", sa.Text(), nullable=False),
        sa.Column("confirm_warnings", sa.Boolean(), nullable=False),
        sa.Column("result", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("idempotent_replay", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["import_batches.batch_id"],
            name="fk_publication_audits_batch_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_publication_audits_dataset_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.dataset_version_id"],
            name="fk_publication_audits_dataset_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("publication_audit_id", name="pk_publication_audits"),
    )
    op.create_index(
        "ix_publication_audits_batch_created_at",
        "publication_audits",
        ["batch_id", "created_at"],
    )


def _create_triggers() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_dataset_versions_published_no_update
        BEFORE UPDATE ON dataset_versions
        WHEN OLD.status = 'PUBLISHED'
        BEGIN
            SELECT RAISE(ABORT, 'PUBLISHED_DATASET_VERSION_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dataset_versions_published_no_delete
        BEFORE DELETE ON dataset_versions
        WHEN OLD.status = 'PUBLISHED'
        BEGIN
            SELECT RAISE(ABORT, 'PUBLISHED_DATASET_VERSION_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dataset_files_published_no_update
        BEFORE UPDATE ON dataset_files
        WHEN EXISTS (
            SELECT 1 FROM dataset_versions
            WHERE dataset_version_id = OLD.dataset_version_id
              AND status = 'PUBLISHED'
        )
        BEGIN
            SELECT RAISE(ABORT, 'PUBLISHED_DATASET_FILE_IMMUTABLE');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_dataset_files_published_no_delete
        BEFORE DELETE ON dataset_files
        WHEN EXISTS (
            SELECT 1 FROM dataset_versions
            WHERE dataset_version_id = OLD.dataset_version_id
              AND status = 'PUBLISHED'
        )
        BEGIN
            SELECT RAISE(ABORT, 'PUBLISHED_DATASET_FILE_IMMUTABLE');
        END
        """
    )


def upgrade() -> None:
    _extend_import_batches()
    _upgrade_issues()
    _create_tables()
    _create_triggers()


def downgrade() -> None:
    for trigger in _TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    op.drop_index("ix_publication_audits_batch_created_at", table_name="publication_audits")
    op.drop_table("publication_audits")
    op.drop_index("ix_dataset_files_dataset_version_id", table_name="dataset_files")
    op.drop_table("dataset_files")
    op.drop_index("ix_dataset_versions_source_batch_id", table_name="dataset_versions")
    op.drop_index("ix_dataset_versions_dataset_status", table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index("ix_datasets_is_active", table_name="datasets")
    op.drop_table("datasets")

    with op.batch_alter_table("import_batches") as batch_op:
        batch_op.drop_column("preview_completed_at")
        batch_op.drop_column("preview_fingerprint")
        batch_op.drop_column("preview_fingerprint_version")
        batch_op.drop_column("quality_rules_version")
        batch_op.drop_column("normalization_version")
        batch_op.drop_column("provider_version")
        batch_op.drop_column("field_mapping_json")
        batch_op.drop_column("source_file_size")

    _downgrade_issues()
