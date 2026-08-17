from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from quant_lab.db.sqlite import Base


class ResearchExperimentModel(Base):
    __tablename__ = "research_experiments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    market_data_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_data_profiles.profile_id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentRunLinkModel(Base):
    __tablename__ = "experiment_run_links"
    __table_args__ = (UniqueConstraint("experiment_id", "backtest_run_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("research_experiments.id", ondelete="CASCADE"), nullable=False
    )
    backtest_run_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_runs.backtest_run_id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchJournalEntryModel(Base):
    __tablename__ = "research_journal_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    experiment_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_experiments.id", ondelete="SET NULL")
    )
    backtest_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("backtest_runs.backtest_run_id", ondelete="SET NULL")
    )
    strategy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="SET NULL")
    )
    tags_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
