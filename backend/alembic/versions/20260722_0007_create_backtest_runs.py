# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0007"
down_revision: str | None = "20260722_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("backtest_run_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "market_data_profile_id",
            sa.String(36),
            sa.ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("market_data_snapshot_json", sa.Text(), nullable=False),
        sa.Column("market_data_snapshot_fingerprint", sa.String(64), nullable=False),
        sa.Column("strategy_type", sa.String(64), nullable=False),
        sa.Column("strategy_spec_json", sa.Text(), nullable=False),
        sa.Column("strategy_fingerprint", sa.String(64), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("run_input_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("initial_cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_message", sa.Text()),
        sa.Column("artifact_manifest_path", sa.String(1024)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "backtest_artifacts",
        sa.Column("backtest_artifact_id", sa.String(36), primary_key=True),
        sa.Column(
            "backtest_run_id",
            sa.String(36),
            sa.ForeignKey("backtest_runs.backtest_run_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("backtest_run_id", "artifact_type"),
        sa.UniqueConstraint("backtest_run_id", "relative_path"),
    )
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_succeeded_no_update
        BEFORE UPDATE ON backtest_runs
        WHEN OLD.status = 'SUCCEEDED'
        BEGIN SELECT RAISE(ABORT, 'SUCCEEDED backtest run is immutable'); END;
    """)
    op.execute("""
        CREATE TRIGGER trg_backtest_runs_succeeded_no_delete
        BEFORE DELETE ON backtest_runs
        WHEN OLD.status = 'SUCCEEDED'
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


def downgrade() -> None:
    for name in (
        "trg_backtest_artifacts_succeeded_no_delete",
        "trg_backtest_artifacts_succeeded_no_update",
        "trg_backtest_artifacts_succeeded_no_insert",
        "trg_backtest_runs_succeeded_no_delete",
        "trg_backtest_runs_succeeded_no_update",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_table("backtest_artifacts")
    op.drop_table("backtest_runs")
