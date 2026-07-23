# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0009"
down_revision: str | None = "20260722_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _drop_backtest_triggers()
    with op.batch_alter_table("backtest_runs") as batch:
        batch.add_column(sa.Column("strategy_version_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_backtest_runs_strategy_version",
            "strategy_versions",
            ["strategy_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    _create_backtest_triggers()


def downgrade() -> None:
    _drop_backtest_triggers()
    with op.batch_alter_table("backtest_runs") as batch:
        batch.drop_constraint("fk_backtest_runs_strategy_version", type_="foreignkey")
        batch.drop_column("strategy_version_id")
    _create_backtest_triggers()


def _drop_backtest_triggers() -> None:
    for name in (
        "trg_backtest_artifacts_succeeded_no_delete",
        "trg_backtest_artifacts_succeeded_no_update",
        "trg_backtest_artifacts_succeeded_no_insert",
        "trg_backtest_runs_succeeded_no_delete",
        "trg_backtest_runs_succeeded_no_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _create_backtest_triggers() -> None:
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_succeeded_no_update
        BEFORE UPDATE ON backtest_runs WHEN OLD.status = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest run is immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_succeeded_no_delete
        BEFORE DELETE ON backtest_runs WHEN OLD.status = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest run is immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_artifacts_succeeded_no_insert
        BEFORE INSERT ON backtest_artifacts
        WHEN (SELECT status FROM backtest_runs WHERE backtest_run_id = NEW.backtest_run_id) = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest artifacts are immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_artifacts_succeeded_no_update
        BEFORE UPDATE ON backtest_artifacts
        WHEN (SELECT status FROM backtest_runs WHERE backtest_run_id = OLD.backtest_run_id) = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest artifacts are immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_artifacts_succeeded_no_delete
        BEFORE DELETE ON backtest_artifacts
        WHEN (SELECT status FROM backtest_runs WHERE backtest_run_id = OLD.backtest_run_id) = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest artifacts are immutable'); END;
    """)
