from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260910_0016"
down_revision: str | None = "20260830_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOKENS = ("prompt_tokens", "cached_prompt_tokens", "completion_tokens", "total_tokens")


def _protect(table: str) -> None:
    for action in ("update", "delete"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_{action} BEFORE {action.upper()} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
        )


def _usage_nullable(nullable: bool) -> None:
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_ai_usage_ledger_no_{action}")
    with op.batch_alter_table("ai_usage_ledger") as batch:
        for column in TOKENS:
            batch.alter_column(column, existing_type=sa.Integer(), nullable=nullable)
    _protect("ai_usage_ledger")


def upgrade() -> None:
    _usage_nullable(True)
    op.create_table(
        "ai_provider_call_bindings",
        sa.Column(
            "attempt_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_attempts.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("binding_json", sa.Text(), nullable=False),
        sa.Column("reserved_cost", sa.Numeric(20, 8)),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reserved_cost IS NULL OR reserved_cost >= 0", name="ck_ai_provider_reserved_cost"
        ),
    )
    op.create_index("ix_ai_provider_call_bindings_run_id", "ai_provider_call_bindings", ["run_id"])
    _protect("ai_provider_call_bindings")


def downgrade() -> None:
    connection = op.get_bind()
    unknown = connection.scalar(
        sa.text(
            "SELECT count(*) FROM ai_usage_ledger WHERE "
            + " OR ".join(f"{column} IS NULL" for column in TOKENS)
        )
    )
    bindings = connection.scalar(sa.text("SELECT count(*) FROM ai_provider_call_bindings"))
    if unknown or bindings:
        raise RuntimeError("AI_PROVIDER_DOWNGRADE_WOULD_LOSE_PROVENANCE")
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER trg_ai_provider_call_bindings_no_{action}")
    op.drop_index("ix_ai_provider_call_bindings_run_id", table_name="ai_provider_call_bindings")
    op.drop_table("ai_provider_call_bindings")
    _usage_nullable(False)
