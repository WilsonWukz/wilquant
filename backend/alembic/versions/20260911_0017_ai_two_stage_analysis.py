from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_0017"
down_revision: str | None = "20260910_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "ai_analysis_orchestrations",
    "ai_analysis_execution_epochs",
    "ai_analysis_stage_bindings",
    "ai_analysis_context_freezes",
)
ATTEMPT_COLUMNS = (
    "stage",
    "parent_attempt_id",
    "retry_reason_codes_json",
    "validation_feedback_fingerprint",
)


def _immutable(table: str, columns: tuple[str, ...], suffix: str = "identity") -> None:
    condition = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
    op.execute(
        f"CREATE TRIGGER trg_{table}_{suffix} BEFORE UPDATE ON {table} WHEN {condition} "
        "BEGIN SELECT RAISE(ABORT, 'AI analysis identity is immutable'); END"
    )


def upgrade() -> None:
    op.execute("""CREATE TABLE ai_analysis_context_freezes (
        create_key VARCHAR(128) PRIMARY KEY,
        submitted_request_fingerprint VARCHAR(64) NOT NULL,
        request_artifact_json TEXT NOT NULL, owner_id VARCHAR(36) NOT NULL,
        status VARCHAR(16) NOT NULL CHECK(status IN ('OBSERVING','FROZEN','FAILED')),
        observation_artifact_json TEXT, run_id VARCHAR(36) REFERENCES ai_analysis_runs(id),
        failure_code VARCHAR(64), created_at DATETIME NOT NULL)""")
    _immutable(
        "ai_analysis_context_freezes",
        (
            "create_key",
            "submitted_request_fingerprint",
            "request_artifact_json",
            "owner_id",
            "created_at",
        ),
    )
    op.execute("""CREATE TRIGGER trg_ai_analysis_context_freezes_terminal
        BEFORE UPDATE ON ai_analysis_context_freezes WHEN OLD.status!='OBSERVING'
        BEGIN SELECT RAISE(ABORT, 'AI context freeze is terminal'); END""")
    op.execute("""CREATE TRIGGER trg_ai_analysis_context_freezes_observation
        BEFORE UPDATE ON ai_analysis_context_freezes
        WHEN OLD.observation_artifact_json IS NOT NULL
        AND OLD.observation_artifact_json IS NOT NEW.observation_artifact_json
        BEGIN SELECT RAISE(ABORT, 'AI observation is immutable'); END""")
    op.execute(
        "ALTER TABLE ai_analysis_attempts ADD COLUMN stage VARCHAR(32) "
        "CHECK (stage IS NULL OR stage IN ('STAGE_1_DIAGNOSIS','STAGE_2_RECOMMENDATION'))"
    )
    op.execute(
        "ALTER TABLE ai_analysis_attempts ADD COLUMN parent_attempt_id VARCHAR(36) "
        "REFERENCES ai_analysis_attempts(id) ON DELETE RESTRICT"
    )
    op.add_column("ai_analysis_attempts", sa.Column("retry_reason_codes_json", sa.Text()))
    op.add_column(
        "ai_analysis_attempts", sa.Column("validation_feedback_fingerprint", sa.String(64))
    )
    _immutable("ai_analysis_attempts", ATTEMPT_COLUMNS, "stage_identity")
    op.execute("""CREATE TRIGGER trg_ai_analysis_attempts_lineage
        BEFORE INSERT ON ai_analysis_attempts
        WHEN NEW.parent_attempt_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM ai_analysis_attempts p WHERE p.id=NEW.parent_attempt_id
          AND p.run_id=NEW.run_id AND p.stage=NEW.stage AND p.attempt_number<NEW.attempt_number)
        BEGIN SELECT RAISE(ABORT, 'AI retry lineage invalid'); END""")
    op.execute("""CREATE TABLE ai_analysis_orchestrations (
        run_id VARCHAR(36) PRIMARY KEY REFERENCES ai_analysis_runs(id),
        create_key VARCHAR(128) NOT NULL UNIQUE, request_fingerprint VARCHAR(64) NOT NULL,
        request_artifact_json TEXT NOT NULL, context_json TEXT NOT NULL,
        progress VARCHAR(32) NOT NULL CHECK(progress IN ('CONTEXT_PREPARED','STAGE1_PENDING',
            'STAGE1_ACCEPTED','STAGE_GATE_DECIDED','STAGE2_PENDING','STAGE2_ACCEPTED','TERMINAL')),
        outcome VARCHAR(32) CHECK(outcome IS NULL OR outcome IN ('PROCEEDED','WAIT_FOR_EVIDENCE',
            'ABSTAINED','REJECTED','PROVIDER_FAILED','VALIDATION_FAILED','BUDGET_BLOCKED',
            'CANCELLED','PROVIDER_RESULT_UNKNOWN')),
        active_epoch_id VARCHAR(36), diagnosis_json TEXT, recommendation_json TEXT, gate_json TEXT,
        provider_result_unknown BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME NOT NULL)""")
    op.execute("""CREATE TABLE ai_analysis_execution_epochs (
        id VARCHAR(36) PRIMARY KEY, run_id VARCHAR(36) NOT NULL REFERENCES ai_analysis_runs(id),
        idempotency_key VARCHAR(128) NOT NULL, payload_fingerprint VARCHAR(64) NOT NULL,
        intent VARCHAR(32) NOT NULL CHECK(intent IN ('INITIAL','RESUME','RETRY_UNKNOWN')),
        status VARCHAR(32) NOT NULL
            CHECK(status IN ('ACTIVE','COMPLETED','INTERRUPTED','CANCELLED')),
        created_at DATETIME NOT NULL, completed_at DATETIME,
        UNIQUE(run_id,idempotency_key))""")
    op.execute(
        "CREATE UNIQUE INDEX ix_ai_analysis_single_active_epoch "
        "ON ai_analysis_execution_epochs(run_id) WHERE status='ACTIVE'"
    )
    op.execute("""CREATE TABLE ai_analysis_stage_bindings (
        attempt_id VARCHAR(36) PRIMARY KEY REFERENCES ai_analysis_attempts(id),
        run_id VARCHAR(36) NOT NULL REFERENCES ai_analysis_runs(id),
        epoch_id VARCHAR(36) NOT NULL REFERENCES ai_analysis_execution_epochs(id),
        binding_json TEXT NOT NULL, fingerprint VARCHAR(64) NOT NULL,
        created_at DATETIME NOT NULL)""")
    op.execute("""CREATE TRIGGER trg_ai_analysis_stage_bindings_relationship
        BEFORE INSERT ON ai_analysis_stage_bindings WHEN NOT EXISTS (
          SELECT 1 FROM ai_analysis_attempts a
          JOIN ai_analysis_execution_epochs e ON e.id=NEW.epoch_id AND e.run_id=a.run_id
          JOIN ai_analysis_orchestrations o ON o.run_id=a.run_id AND o.active_epoch_id=e.id
          WHERE a.id=NEW.attempt_id AND a.run_id=NEW.run_id AND a.stage IS NOT NULL
          AND a.status='STARTED' AND e.status='ACTIVE' AND o.progress!='TERMINAL')
        BEGIN SELECT RAISE(ABORT, 'AI binding relationship invalid'); END""")
    _immutable(
        TABLES[0],
        (
            "run_id",
            "create_key",
            "request_fingerprint",
            "request_artifact_json",
            "context_json",
            "created_at",
        ),
    )
    _immutable(
        TABLES[1],
        ("id", "run_id", "idempotency_key", "payload_fingerprint", "intent", "created_at"),
    )
    _immutable(
        TABLES[2], ("attempt_id", "run_id", "epoch_id", "binding_json", "fingerprint", "created_at")
    )
    for field in ("diagnosis_json", "recommendation_json", "gate_json"):
        op.execute(
            f"CREATE TRIGGER trg_ai_analysis_orchestrations_{field} "
            "BEFORE UPDATE ON ai_analysis_orchestrations "
            f"WHEN OLD.{field} IS NOT NULL AND OLD.{field} IS NOT NEW.{field} "
            "BEGIN SELECT RAISE(ABORT, 'AI accepted history is immutable'); END"
        )
    for field, stage in (
        ("diagnosis_json", "STAGE_1_DIAGNOSIS"),
        ("recommendation_json", "STAGE_2_RECOMMENDATION"),
    ):
        op.execute(f"""CREATE TRIGGER trg_ai_analysis_orchestrations_{field}_validation
            BEFORE UPDATE ON ai_analysis_orchestrations
            WHEN NEW.{field} IS NOT NULL AND OLD.{field} IS NULL AND NOT EXISTS (
              SELECT 1 FROM ai_validation_results v
              JOIN ai_analysis_attempts a ON a.id=v.attempt_id AND a.run_id=v.run_id
              WHERE v.id=json_extract(NEW.{field}, '$.validation_result_id')
              AND v.attempt_id=json_extract(NEW.{field}, '$.attempt_id')
              AND v.run_id=NEW.run_id AND v.disposition='ACCEPTED'
              AND a.stage='{stage}' AND a.status='COMPLETED'
              AND v.evidence_pack_id=json_extract(NEW.context_json, '$.evidence_pack_id'))
            BEGIN SELECT RAISE(ABORT, 'AI accepted validation linkage invalid'); END""")
    op.execute("""CREATE TRIGGER trg_ai_analysis_orchestrations_terminal
        BEFORE UPDATE ON ai_analysis_orchestrations
        WHEN OLD.progress='TERMINAL' BEGIN SELECT RAISE(ABORT, 'AI analysis is terminal'); END""")
    op.execute("""CREATE TRIGGER trg_ai_analysis_execution_epochs_terminal
        BEFORE UPDATE ON ai_analysis_execution_epochs
        WHEN OLD.status!='ACTIVE'
        BEGIN SELECT RAISE(ABORT, 'AI execution epoch is terminal'); END""")
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'AI analysis history cannot be deleted'); END"
        )


def downgrade() -> None:
    conn = op.get_bind()
    if any(
        conn.scalar(sa.text(f"SELECT count(*) FROM {table}")) for table in TABLES
    ) or conn.scalar(
        sa.text(
            "SELECT count(*) FROM ai_analysis_attempts WHERE stage IS NOT NULL "
            "OR parent_attempt_id IS NOT NULL OR retry_reason_codes_json IS NOT NULL "
            "OR validation_feedback_fingerprint IS NOT NULL"
        )
    ):
        raise RuntimeError("AI_ANALYSIS_DOWNGRADE_WOULD_LOSE_PROVENANCE")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.execute("DROP TRIGGER trg_ai_analysis_attempts_stage_identity")
    op.execute("DROP TRIGGER trg_ai_analysis_attempts_lineage")
    for column in reversed(ATTEMPT_COLUMNS):
        op.execute(f"ALTER TABLE ai_analysis_attempts DROP COLUMN {column}")
