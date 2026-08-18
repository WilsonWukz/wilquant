from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0013"
down_revision: str | None = "20260722_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical-replay range. replay_start_date is NOT NULL with a sentinel
    # default so pre-existing 0012 sessions migrate cleanly; new sessions always
    # pass an explicit replay_start_date through PaperSessionService.
    op.add_column(
        "paper_sessions",
        sa.Column(
            "replay_start_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("'1970-01-01'"),
        ),
    )
    op.add_column("paper_sessions", sa.Column("replay_end_date", sa.Date(), nullable=True))
    # Frozen execution settings (fee/slippage/volume participation).
    op.add_column(
        "paper_sessions",
        sa.Column(
            "execution_config_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "paper_sessions",
        sa.Column(
            "execution_config_fingerprint",
            sa.String(64),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )

    # Failure semantics for idempotent advance records.
    op.add_column("paper_session_advances", sa.Column("error_code", sa.String(64), nullable=True))

    # gross_exposure must match the 5B RiskAccountSnapshot semantics: it is an
    # amount (== market_value), not a ratio, so widen it to the money precision.
    with op.batch_alter_table("paper_account_snapshots") as batch_op:
        batch_op.alter_column(
            "gross_exposure",
            existing_type=sa.Numeric(10, 6),
            type_=sa.Numeric(20, 8),
            existing_nullable=False,
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_account_snapshots") as batch_op:
        batch_op.alter_column(
            "gross_exposure",
            existing_type=sa.Numeric(20, 8),
            type_=sa.Numeric(10, 6),
            existing_nullable=False,
            nullable=False,
        )
    op.drop_column("paper_session_advances", "error_code")
    op.drop_column("paper_sessions", "execution_config_fingerprint")
    op.drop_column("paper_sessions", "execution_config_json")
    op.drop_column("paper_sessions", "replay_end_date")
    op.drop_column("paper_sessions", "replay_start_date")
