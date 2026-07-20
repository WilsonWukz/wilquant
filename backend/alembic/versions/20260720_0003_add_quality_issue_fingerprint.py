"""Add stable identity and uniqueness for data-quality issues."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260720_0003"
down_revision: str | None = "20260720_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "uq_data_quality_issues_batch_fingerprint"


def _fingerprint(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        [
            row["row_number"],
            row["symbol"],
            row["field_name"],
            row["severity"],
            row["issue_code"],
            row["message"],
            row["raw_value"],
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column(
        "data_quality_issues",
        sa.Column("issue_fingerprint", sa.String(64), nullable=True),
    )
    issues = sa.table(
        "data_quality_issues",
        sa.column("issue_id", sa.String(36)),
        sa.column("batch_id", sa.String(36)),
        sa.column("row_number", sa.Integer()),
        sa.column("symbol", sa.String(16)),
        sa.column("field_name", sa.String(100)),
        sa.column("severity", sa.String(16)),
        sa.column("issue_code", sa.String(64)),
        sa.column("message", sa.Text()),
        sa.column("raw_value", sa.Text()),
        sa.column("issue_fingerprint", sa.String(64)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(issues).order_by(issues.c.created_at, issues.c.issue_id)
    ).mappings()
    seen: set[tuple[str, str]] = set()
    for row in rows:
        fingerprint = _fingerprint(row)
        identity = (row["batch_id"], fingerprint)
        if identity in seen:
            connection.execute(sa.delete(issues).where(issues.c.issue_id == row["issue_id"]))
            continue
        seen.add(identity)
        connection.execute(
            sa.update(issues)
            .where(issues.c.issue_id == row["issue_id"])
            .values(issue_fingerprint=fingerprint)
        )

    with op.batch_alter_table("data_quality_issues") as batch_op:
        batch_op.alter_column(
            "issue_fingerprint",
            existing_type=sa.String(64),
            nullable=False,
        )
    op.create_index(
        _INDEX_NAME,
        "data_quality_issues",
        ["batch_id", "issue_fingerprint"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="data_quality_issues")
    with op.batch_alter_table("data_quality_issues") as batch_op:
        batch_op.drop_column("issue_fingerprint")
