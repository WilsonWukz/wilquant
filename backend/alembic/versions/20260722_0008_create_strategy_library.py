from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0008"
down_revision: str | None = "20260722_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("strategy_definitions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text(), nullable=False), sa.Column("strategy_type", sa.String(64), nullable=False), sa.Column("status", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("strategy_versions", sa.Column("id", sa.String(36), primary_key=True), sa.Column("strategy_definition_id", sa.String(36), sa.ForeignKey("strategy_definitions.id", ondelete="RESTRICT"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("strategy_spec_json", sa.Text(), nullable=False), sa.Column("strategy_fingerprint", sa.String(64), nullable=False), sa.Column("change_note", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("strategy_definition_id", "version"))
    op.execute("CREATE TRIGGER trg_strategy_versions_immutable BEFORE UPDATE ON strategy_versions BEGIN SELECT RAISE(ABORT, 'strategy version immutable'); END;")
    op.execute("CREATE TRIGGER trg_strategy_versions_no_delete BEFORE DELETE ON strategy_versions BEGIN SELECT RAISE(ABORT, 'strategy version immutable'); END;")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_strategy_versions_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_strategy_versions_immutable")
    op.drop_table("strategy_versions"); op.drop_table("strategy_definitions")
