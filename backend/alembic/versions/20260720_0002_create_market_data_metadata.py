"""Create market-data control-plane metadata tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0002"
down_revision: str | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("instrument_id", sa.String(32), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("exchange", sa.String(16), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("instrument_type", sa.String(32), nullable=False),
        sa.Column("board", sa.String(32)),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("price_tick", sa.Numeric(20, 8), nullable=False),
        sa.Column("listing_date", sa.Date()),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("is_st", sa.Boolean(), nullable=False),
        sa.Column("supports_t0", sa.Boolean(), nullable=False),
        sa.Column("data_source", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_instruments_symbol_exchange", "instruments", ["symbol", "exchange"])

    op.create_table(
        "data_sources",
        sa.Column("source_id", sa.String(36), primary_key=True),
        sa.Column("identifier", sa.String(100), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("is_local", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("original_file", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "import_batches",
        sa.Column("batch_id", sa.String(36), primary_key=True),
        sa.Column("data_source_id", sa.String(36), nullable=False),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("source_name", sa.String(255), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column("source_file_hash", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_summary", sa.Text()),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.source_id"]),
        sa.UniqueConstraint("source_file_hash", name="uq_import_batches_source_file_hash"),
    )
    op.create_index("ix_import_batches_status", "import_batches", ["status"])

    op.create_table(
        "data_quality_issues",
        sa.Column("issue_id", sa.String(36), primary_key=True),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("row_number", sa.Integer()),
        sa.Column("symbol", sa.String(16)),
        sa.Column("field_name", sa.String(100)),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("issue_code", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("raw_value", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["import_batches.batch_id"]),
    )
    op.create_index(
        "ix_data_quality_issues_batch_id", "data_quality_issues", ["batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_data_quality_issues_batch_id", table_name="data_quality_issues")
    op.drop_table("data_quality_issues")
    op.drop_index("ix_import_batches_status", table_name="import_batches")
    op.drop_table("import_batches")
    op.drop_table("data_sources")
    op.drop_index("ix_instruments_symbol_exchange", table_name="instruments")
    op.drop_table("instruments")
