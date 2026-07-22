from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0006"
down_revision: str | None = "20260722_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_data_profiles",
        sa.Column("profile_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("bar_frequency", sa.String(32), nullable=False),
        sa.Column("bars_dataset_id", sa.String(36), sa.ForeignKey("datasets.dataset_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bars_dataset_version_id", sa.String(36), sa.ForeignKey("dataset_versions.dataset_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("calendar_id", sa.String(36), sa.ForeignKey("trading_calendars.calendar_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("calendar_version_id", sa.String(36), sa.ForeignKey("trading_calendar_versions.trading_calendar_version_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "market_data_profile_audits",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.String(36), sa.ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_data_profile_audits")
    op.drop_table("market_data_profiles")
