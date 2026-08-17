
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0010"
down_revision: str | None = "20260722_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_experiments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column(
            "market_data_profile_id",
            sa.String(36),
            sa.ForeignKey("market_data_profiles.profile_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "experiment_run_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(36),
            sa.ForeignKey("research_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "backtest_run_id",
            sa.String(36),
            sa.ForeignKey("backtest_runs.backtest_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("experiment_id", "backtest_run_id"),
    )
    op.create_index(
        "ux_experiment_single_baseline",
        "experiment_run_links",
        ["experiment_id"],
        unique=True,
        sqlite_where=sa.text("role = 'BASELINE'"),
    )
    op.create_table(
        "research_journal_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "experiment_id",
            sa.String(36),
            sa.ForeignKey("research_experiments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "backtest_run_id",
            sa.String(36),
            sa.ForeignKey("backtest_runs.backtest_run_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "strategy_version_id",
            sa.String(36),
            sa.ForeignKey("strategy_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("research_journal_entries")
    op.drop_index("ux_experiment_single_baseline", table_name="experiment_run_links")
    op.drop_table("experiment_run_links")
    op.drop_table("research_experiments")
