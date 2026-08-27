from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260827_0014"
down_revision: str | None = "20260722_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FULLY_IMMUTABLE_TABLES = (
    "ai_prompt_template_versions",
    "ai_model_config_versions",
    "ai_research_cases",
    "ai_evidence_refs",
    "ai_analysis_trace_events",
    "ai_usage_ledger",
)


def _immutable_triggers(table_name: str) -> None:
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_no_update BEFORE UPDATE ON {table_name} "
        f"BEGIN SELECT RAISE(ABORT, '{table_name} is immutable'); END"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table_name}_no_delete BEFORE DELETE ON {table_name} "
        f"BEGIN SELECT RAISE(ABORT, '{table_name} is immutable'); END"
    )


def upgrade() -> None:
    op.create_table(
        "ai_prompt_template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("variable_contract_json", sa.Text(), nullable=False),
        sa.Column("variable_contract_sha256", sa.String(64), nullable=False),
        sa.Column("validator_policy_version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_model_config_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_kind", sa.String(64), nullable=False),
        sa.Column("provider_id", sa.String(100), nullable=False),
        sa.Column("base_url_identity", sa.String(255), nullable=False),
        sa.Column("model_identifier", sa.String(255), nullable=False),
        sa.Column("endpoint_profile_id", sa.String(100), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("parameters_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_research_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("instrument_id", sa.String(100), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("timeframe", sa.String(32), nullable=False),
        sa.Column("as_of_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_local_trade_date", sa.Date(), nullable=False),
        sa.Column("bindings_json", sa.Text(), nullable=False),
        sa.Column(
            "previous_case_id",
            sa.String(36),
            sa.ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
        ),
        sa.Column("previous_analysis_run_id", sa.String(36)),
        sa.Column("thesis_revision_id", sa.String(36)),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_evidence_refs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(64), nullable=False),
        sa.Column("source_entity_type", sa.String(64), nullable=False),
        sa.Column("source_entity_id", sa.String(100), nullable=False),
        sa.Column("source_version_id", sa.String(100), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("locator_json", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market", sa.String(32), nullable=False),
        sa.Column("instrument_id", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("temporal_status", sa.String(32), nullable=False),
        sa.Column("integrity_status", sa.String(32), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "ai_analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(36),
            sa.ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "parent_run_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "prompt_template_version_id",
            sa.String(36),
            sa.ForeignKey("ai_prompt_template_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "model_config_version_id",
            sa.String(36),
            sa.ForeignKey("ai_model_config_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("case_fingerprint", sa.String(64), nullable=False),
        sa.Column("prompt_template_fingerprint", sa.String(64), nullable=False),
        sa.Column("resolved_prompt_fingerprint", sa.String(64), nullable=False),
        sa.Column("model_config_fingerprint", sa.String(64), nullable=False),
        sa.Column("validator_policy_version", sa.String(64), nullable=False),
        sa.Column("validator_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_envelope_fingerprint", sa.String(64)),
        sa.Column("raw_response_artifact_sha256", sa.String(64)),
        sa.Column("normalized_output_fingerprint", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("safe_failure_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN "
            "('CREATED','RUNNING','VALIDATING','COMPLETED','FAILED','CANCELLED','REJECTED')",
            name="ck_ai_analysis_runs_status",
        ),
    )
    op.create_table(
        "ai_analysis_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("output_fingerprint", sa.String(64)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("finish_reason", sa.String(64)),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", "attempt_number"),
        sa.CheckConstraint(
            "status IN ('STARTED','COMPLETED','FAILED','ABANDONED')",
            name="ck_ai_analysis_attempts_status",
        ),
    )
    op.create_table(
        "ai_analysis_trace_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_fingerprint", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence"),
    )
    op.create_table(
        "ai_usage_ledger",
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
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("reported_cost", sa.Numeric(20, 8)),
        sa.Column("estimated_cost", sa.Numeric(20, 8)),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("is_estimate", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND cached_prompt_tokens >= 0 AND "
            "completion_tokens >= 0 AND total_tokens >= 0",
            name="ck_ai_usage_non_negative",
        ),
        sa.CheckConstraint(
            "(reported_cost IS NULL OR reported_cost >= 0) AND "
            "(estimated_cost IS NULL OR estimated_cost >= 0)",
            name="ck_ai_usage_cost_non_negative",
        ),
    )

    for table_name in _FULLY_IMMUTABLE_TABLES:
        _immutable_triggers(table_name)

    op.execute(
        "CREATE TRIGGER trg_ai_analysis_runs_identity_immutable "
        "BEFORE UPDATE ON ai_analysis_runs WHEN "
        "OLD.case_id IS NOT NEW.case_id OR OLD.stage IS NOT NEW.stage OR "
        "OLD.parent_run_id IS NOT NEW.parent_run_id OR "
        "OLD.prompt_template_version_id IS NOT NEW.prompt_template_version_id OR "
        "OLD.model_config_version_id IS NOT NEW.model_config_version_id OR "
        "OLD.case_fingerprint IS NOT NEW.case_fingerprint OR "
        "OLD.prompt_template_fingerprint IS NOT NEW.prompt_template_fingerprint OR "
        "OLD.resolved_prompt_fingerprint IS NOT NEW.resolved_prompt_fingerprint OR "
        "OLD.model_config_fingerprint IS NOT NEW.model_config_fingerprint OR "
        "OLD.validator_policy_version IS NOT NEW.validator_policy_version OR "
        "OLD.validator_policy_fingerprint IS NOT NEW.validator_policy_fingerprint OR "
        "(OLD.input_envelope_fingerprint IS NOT NULL AND "
        "OLD.input_envelope_fingerprint IS NOT NEW.input_envelope_fingerprint) "
        "BEGIN SELECT RAISE(ABORT, 'ai_analysis_run identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_runs_invalid_transition "
        "BEFORE UPDATE OF status ON ai_analysis_runs WHEN NOT ("
        "OLD.status = NEW.status OR "
        "(OLD.status = 'CREATED' AND NEW.status IN ('RUNNING','CANCELLED')) OR "
        "(OLD.status = 'RUNNING' AND NEW.status IN "
        "('VALIDATING','COMPLETED','FAILED','CANCELLED','REJECTED')) OR "
        "(OLD.status = 'VALIDATING' AND NEW.status IN "
        "('COMPLETED','FAILED','CANCELLED','REJECTED'))) "
        "BEGIN SELECT RAISE(ABORT, 'invalid ai_analysis_run transition'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_runs_terminal_no_update "
        "BEFORE UPDATE ON ai_analysis_runs WHEN OLD.status IN "
        "('COMPLETED','FAILED','CANCELLED','REJECTED') "
        "BEGIN SELECT RAISE(ABORT, 'terminal ai_analysis_run is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_runs_no_delete BEFORE DELETE ON ai_analysis_runs "
        "BEGIN SELECT RAISE(ABORT, 'ai_analysis_runs cannot be deleted'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_attempts_identity_immutable "
        "BEFORE UPDATE ON ai_analysis_attempts WHEN "
        "OLD.run_id IS NOT NEW.run_id OR OLD.attempt_number IS NOT NEW.attempt_number OR "
        "OLD.input_fingerprint IS NOT NEW.input_fingerprint OR "
        "OLD.started_at IS NOT NEW.started_at "
        "BEGIN SELECT RAISE(ABORT, 'ai_analysis_attempt identity is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_attempts_invalid_transition "
        "BEFORE UPDATE OF status ON ai_analysis_attempts WHEN NOT ("
        "OLD.status = 'STARTED' AND NEW.status IN ('COMPLETED','FAILED','ABANDONED')) "
        "BEGIN SELECT RAISE(ABORT, 'invalid ai_analysis_attempt transition'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_attempts_terminal_no_update "
        "BEFORE UPDATE ON ai_analysis_attempts WHEN OLD.status IN "
        "('COMPLETED','FAILED','ABANDONED') "
        "BEGIN SELECT RAISE(ABORT, 'terminal ai_analysis_attempt is immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_ai_analysis_attempts_no_delete "
        "BEFORE DELETE ON ai_analysis_attempts "
        "BEGIN SELECT RAISE(ABORT, 'ai_analysis_attempts cannot be deleted'); END"
    )


def downgrade() -> None:
    trigger_names = [
        "trg_ai_analysis_attempts_no_delete",
        "trg_ai_analysis_attempts_terminal_no_update",
        "trg_ai_analysis_attempts_invalid_transition",
        "trg_ai_analysis_attempts_identity_immutable",
        "trg_ai_analysis_runs_no_delete",
        "trg_ai_analysis_runs_terminal_no_update",
        "trg_ai_analysis_runs_invalid_transition",
        "trg_ai_analysis_runs_identity_immutable",
    ]
    for table_name in reversed(_FULLY_IMMUTABLE_TABLES):
        trigger_names.extend(
            [f"trg_{table_name}_no_delete", f"trg_{table_name}_no_update"]
        )
    for trigger_name in trigger_names:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")

    for table_name in (
        "ai_usage_ledger",
        "ai_analysis_trace_events",
        "ai_analysis_attempts",
        "ai_analysis_runs",
        "ai_evidence_refs",
        "ai_research_cases",
        "ai_model_config_versions",
        "ai_prompt_template_versions",
    ):
        op.drop_table(table_name)
