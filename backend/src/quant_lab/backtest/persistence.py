from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from quant_lab.db.sqlite import Base


class BacktestRunModel(Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (UniqueConstraint("run_input_fingerprint"),)

    backtest_run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    market_data_profile_id: Mapped[str] = mapped_column(
        ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"), nullable=False
    )
    market_data_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    market_data_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_spec_json: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    run_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    artifact_manifest_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BacktestArtifactModel(Base):
    __tablename__ = "backtest_artifacts"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "artifact_type"),
        UniqueConstraint("backtest_run_id", "relative_path"),
    )

    backtest_artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    backtest_run_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_runs.backtest_run_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
