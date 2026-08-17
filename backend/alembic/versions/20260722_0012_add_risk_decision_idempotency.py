from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_0012"
down_revision: str | None = "20260722_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ux_paper_risk_decision_intent",
        "paper_risk_decisions",
        ["order_intent_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_paper_risk_decision_intent", table_name="paper_risk_decisions")
