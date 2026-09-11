from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from quant_lab.db.sqlite import Base


class AIAnalysisContextFreezeModel(Base):
    """Durable create ownership before observing sources; not a second analysis Run."""

    __tablename__ = "ai_analysis_context_freezes"
    create_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    submitted_request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_artifact_json: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observation_artifact_json: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("ai_analysis_runs.id"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIAnalysisOrchestrationModel(Base):
    """One-to-one extension of an existing Run, not another execution lifecycle."""

    __tablename__ = "ai_analysis_orchestrations"
    run_id: Mapped[str] = mapped_column(ForeignKey("ai_analysis_runs.id"), primary_key=True)
    create_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_artifact_json: Mapped[str] = mapped_column(Text, nullable=False)
    context_json: Mapped[str] = mapped_column(Text, nullable=False)
    progress: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(32))
    active_epoch_id: Mapped[str | None] = mapped_column(String(36))
    diagnosis_json: Mapped[str | None] = mapped_column(Text)
    recommendation_json: Mapped[str | None] = mapped_column(Text)
    gate_json: Mapped[str | None] = mapped_column(Text)
    provider_result_unknown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIAnalysisExecutionEpochModel(Base):
    __tablename__ = "ai_analysis_execution_epochs"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ai_analysis_runs.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIAnalysisStageBindingModel(Base):
    __tablename__ = "ai_analysis_stage_bindings"
    attempt_id: Mapped[str] = mapped_column(ForeignKey("ai_analysis_attempts.id"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ai_analysis_runs.id"), nullable=False)
    epoch_id: Mapped[str] = mapped_column(
        ForeignKey("ai_analysis_execution_epochs.id"), nullable=False
    )
    binding_json: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
