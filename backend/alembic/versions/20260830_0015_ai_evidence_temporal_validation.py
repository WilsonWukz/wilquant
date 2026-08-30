from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260830_0015"
down_revision: str | None = "20260827_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HISTORY_TABLES = (
    "ai_evidence_packs",
    "ai_validation_results",
    "ai_research_case_documents",
    "ai_retrieval_snapshots",
)


def _append_only_triggers(table_name: str) -> None:
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_no_update BEFORE UPDATE ON {table_name} "
        f"BEGIN SELECT RAISE(ABORT, '{table_name} is append-only'); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_no_delete BEFORE DELETE ON {table_name} "
        f"BEGIN SELECT RAISE(ABORT, '{table_name} is append-only'); END"
    )


def upgrade() -> None:
    op.create_table(
        "ai_evidence_packs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("temporal_context_json", sa.Text(), nullable=False),
        sa.Column("evidence_context_json", sa.Text(), nullable=False),
        sa.Column("requirements_json", sa.Text(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_evidence_packs_case_id", "ai_evidence_packs", ["case_id"])

    op.create_table(
        "ai_validation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "evidence_pack_id",
            sa.String(36),
            sa.ForeignKey("ai_evidence_packs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("accepted_assertions_json", sa.Text(), nullable=False),
        sa.Column("observations_json", sa.Text(), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('ACCEPTED','REJECTED')",
            name="ck_ai_validation_results_disposition",
        ),
    )
    op.create_index("ix_ai_validation_results_run_id", "ai_validation_results", ["run_id"])
    op.create_index(
        "ix_ai_validation_results_attempt_id", "ai_validation_results", ["attempt_id"]
    )

    op.create_table(
        "ai_research_case_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=False),
        sa.Column("success_factors_json", sa.Text(), nullable=False),
        sa.Column("failure_factors_json", sa.Text(), nullable=False),
        sa.Column("regime_labels_json", sa.Text(), nullable=False),
        sa.Column("safe_tags_json", sa.Text(), nullable=False),
        sa.Column("universe_json", sa.Text(), nullable=False),
        sa.Column("strategy_family", sa.String(100)),
        sa.Column("market_rules_version", sa.String(100)),
        sa.Column("document_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_research_case_documents_case_id", "ai_research_case_documents", ["case_id"]
    )
    op.execute(
        "CREATE VIRTUAL TABLE ai_research_case_fts USING fts5("
        "document_id UNINDEXED, case_id UNINDEXED, title, summary, diagnosis, factors, "
        "labels_tags, tokenize='unicode61 remove_diacritics 2')"
    )

    op.create_table(
        "ai_retrieval_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query_json", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("candidates_json", sa.Text(), nullable=False),
        sa.Column("exclusions_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    for table_name in _HISTORY_TABLES:
        _append_only_triggers(table_name)


def downgrade() -> None:
    for table_name in reversed(_HISTORY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_delete")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_no_update")
    op.drop_table("ai_retrieval_snapshots")
    op.execute("DROP TABLE IF EXISTS ai_research_case_fts")
    op.drop_index(
        "ix_ai_research_case_documents_case_id", table_name="ai_research_case_documents"
    )
    op.drop_table("ai_research_case_documents")
    op.drop_index("ix_ai_validation_results_attempt_id", table_name="ai_validation_results")
    op.drop_index("ix_ai_validation_results_run_id", table_name="ai_validation_results")
    op.drop_table("ai_validation_results")
    op.drop_index("ix_ai_evidence_packs_case_id", table_name="ai_evidence_packs")
    op.drop_table("ai_evidence_packs")
