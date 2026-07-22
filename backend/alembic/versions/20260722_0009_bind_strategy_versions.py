from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0009"
down_revision: str | None = "20260722_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("strategy_version_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_backtest_runs_strategy_version",
            "strategy_versions",
            ["strategy_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_constraint("fk_backtest_runs_strategy_version", type_="foreignkey")
        batch.drop_column("strategy_version_id")
