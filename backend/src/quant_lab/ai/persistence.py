from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from quant_lab.db.sqlite import Base


class AIPromptTemplateVersionModel(Base):
    __tablename__ = "ai_prompt_template_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    variable_contract_json: Mapped[str] = mapped_column(Text, nullable=False)
    variable_contract_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validator_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIModelConfigVersionModel(Base):
    __tablename__ = "ai_model_config_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    model_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint_profile_id: Mapped[str] = mapped_column(String(100), nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIResearchCaseModel(Base):
    __tablename__ = "ai_research_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_local_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    bindings_json: Mapped[str] = mapped_column(Text, nullable=False)
    previous_case_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_research_cases.id", ondelete="RESTRICT")
    )
    previous_analysis_run_id: Mapped[str | None] = mapped_column(String(36))
    thesis_revision_id: Mapped[str | None] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIEvidenceRefModel(Base):
    __tablename__ = "ai_evidence_refs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("ai_research_cases.id", ondelete="RESTRICT"), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version_id: Mapped[str] = mapped_column(String(100), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    locator_json: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    instrument_id: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    temporal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    integrity_status: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIAnalysisRunModel(Base):
    __tablename__ = "ai_analysis_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("ai_research_cases.id", ondelete="RESTRICT"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT")
    )
    prompt_template_version_id: Mapped[str] = mapped_column(
        ForeignKey("ai_prompt_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    model_config_version_id: Mapped[str] = mapped_column(
        ForeignKey("ai_model_config_versions.id", ondelete="RESTRICT"), nullable=False
    )
    case_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_template_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_prompt_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    validator_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    validator_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_envelope_fingerprint: Mapped[str | None] = mapped_column(String(64))
    raw_response_artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    normalized_output_fingerprint: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    safe_failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIAnalysisAttemptModel(Base):
    __tablename__ = "ai_analysis_attempts"
    __table_args__ = (UniqueConstraint("run_id", "attempt_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_fingerprint: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAnalysisTraceEventModel(Base):
    __tablename__ = "ai_analysis_trace_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIUsageLedgerModel(Base):
    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        CheckConstraint(
            "prompt_tokens >= 0 AND cached_prompt_tokens >= 0 AND "
            "completion_tokens >= 0 AND total_tokens >= 0",
            name="ck_ai_usage_non_negative",
        ),
        CheckConstraint(
            "(reported_cost IS NULL OR reported_cost >= 0) AND "
            "(estimated_cost IS NULL OR estimated_cost >= 0)",
            name="ck_ai_usage_cost_non_negative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reported_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    is_estimate: Mapped[bool] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIEvidencePackModel(Base):
    __tablename__ = "ai_evidence_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("ai_research_cases.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    temporal_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    requirements_json: Mapped[str] = mapped_column(Text, nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIValidationResultModel(Base):
    __tablename__ = "ai_validation_results"
    __table_args__ = (
        CheckConstraint(
            "disposition IN ('ACCEPTED','REJECTED')",
            name="ck_ai_validation_results_disposition",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_attempts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    evidence_pack_id: Mapped[str] = mapped_column(
        ForeignKey("ai_evidence_packs.id", ondelete="RESTRICT"), nullable=False
    )
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    findings_json: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_assertions_json: Mapped[str] = mapped_column(Text, nullable=False)
    observations_json: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIResearchCaseDocumentModel(Base):
    __tablename__ = "ai_research_case_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("ai_research_cases.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str] = mapped_column(Text, nullable=False)
    success_factors_json: Mapped[str] = mapped_column(Text, nullable=False)
    failure_factors_json: Mapped[str] = mapped_column(Text, nullable=False)
    regime_labels_json: Mapped[str] = mapped_column(Text, nullable=False)
    safe_tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    universe_json: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_family: Mapped[str | None] = mapped_column(String(100))
    market_rules_version: Mapped[str | None] = mapped_column(String(100))
    document_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIRetrievalSnapshotModel(Base):
    __tablename__ = "ai_retrieval_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    candidates_json: Mapped[str] = mapped_column(Text, nullable=False)
    exclusions_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
