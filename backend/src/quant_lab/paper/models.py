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


class PaperAccountModel(Base):
    __tablename__ = "paper_accounts"
    __table_args__ = (
        CheckConstraint("initial_cash > 0", name="ck_paper_account_initial_cash_positive"),
        CheckConstraint("cash >= 0", name="ck_paper_account_cash_nonnegative"),
        CheckConstraint("market_value >= 0", name="ck_paper_account_market_value_nonnegative"),
        CheckConstraint("account_equity >= 0", name="ck_paper_account_equity_nonnegative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    account_equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperSessionModel(Base):
    __tablename__ = "paper_sessions"
    __table_args__ = (CheckConstraint("version >= 1", name="ck_paper_session_version_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    market_data_profile_id: Mapped[str] = mapped_column(
        ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"), nullable=False
    )
    market_data_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    market_data_snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_session_date: Mapped[date | None] = mapped_column(Date)
    replay_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    replay_end_date: Mapped[date | None] = mapped_column(Date)
    execution_config_json: Mapped[str] = mapped_column(Text, nullable=False)
    execution_config_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperOrderIntentModel(Base):
    __tablename__ = "paper_order_intents"
    __table_args__ = (UniqueConstraint("paper_session_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(36))
    instrument_id: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    signal_session_date: Mapped[date] = mapped_column(Date, nullable=False)
    intended_execution_session: Mapped[date] = mapped_column(Date, nullable=False)
    strategy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("strategy_versions.id", ondelete="RESTRICT")
    )
    reason: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperRiskPolicyModel(Base):
    __tablename__ = "paper_risk_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperRiskPolicyVersionModel(Base):
    __tablename__ = "paper_risk_policy_versions"
    __table_args__ = (UniqueConstraint("risk_policy_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    risk_policy_id: Mapped[str] = mapped_column(
        ForeignKey("paper_risk_policies.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    max_single_order_notional: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    max_single_position_weight: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    max_total_exposure: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    cash_buffer_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    max_daily_loss: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    max_open_orders: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_security_types_json: Mapped[str] = mapped_column(Text, nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperRiskDecisionModel(Base):
    __tablename__ = "paper_risk_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_intent_id: Mapped[str] = mapped_column(
        ForeignKey("paper_order_intents.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_codes_json: Mapped[str] = mapped_column(Text, nullable=False)
    risk_policy_id: Mapped[str] = mapped_column(
        ForeignKey("paper_risk_policies.id", ondelete="RESTRICT"), nullable=False
    )
    risk_policy_version_id: Mapped[str] = mapped_column(
        ForeignKey("paper_risk_policy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    risk_policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    account_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    position_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    market_context_json: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperOrderModel(Base):
    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    paper_session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    order_intent_id: Mapped[str] = mapped_column(
        ForeignKey("paper_order_intents.id", ondelete="RESTRICT"), nullable=False
    )
    risk_decision_id: Mapped[str] = mapped_column(
        ForeignKey("paper_risk_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(32), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    submitted_session_date: Mapped[date | None] = mapped_column(Date)
    execution_session_date: Mapped[date | None] = mapped_column(Date)
    reject_reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperFillModel(Base):
    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_order_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.id", ondelete="RESTRICT"), nullable=False
    )
    paper_session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    slippage: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    commission: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stamp_tax: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    transfer_fee: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_fee: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperPositionModel(Base):
    __tablename__ = "paper_positions"
    __table_args__ = (UniqueConstraint("paper_account_id", "instrument_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(32), nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    sellable_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperPositionLotModel(Base):
    __tablename__ = "paper_position_lots"
    __table_args__ = (
        CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= quantity",
            name="ck_paper_lot_remaining_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    paper_position_id: Mapped[str] = mapped_column(
        ForeignKey("paper_positions.id", ondelete="RESTRICT"), nullable=False
    )
    instrument_id: Mapped[str] = mapped_column(String(32), nullable=False)
    acquired_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    sellable_from_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperAccountSnapshotModel(Base):
    __tablename__ = "paper_account_snapshots"
    __table_args__ = (UniqueConstraint("paper_session_id", "session_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    paper_session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    equity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    gross_exposure: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    daily_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cumulative_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    drawdown: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperLedgerEntryModel(Base):
    __tablename__ = "paper_ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    paper_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT")
    )
    paper_fill_id: Mapped[str | None] = mapped_column(
        ForeignKey("paper_fills.id", ondelete="RESTRICT")
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cash_after: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperAuditEventModel(Base):
    __tablename__ = "paper_audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_account_id: Mapped[str] = mapped_column(
        ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    paper_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT")
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaperSessionAdvanceModel(Base):
    __tablename__ = "paper_session_advances"
    __table_args__ = (UniqueConstraint("paper_session_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    paper_session_id: Mapped[str] = mapped_column(
        ForeignKey("paper_sessions.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_session_date: Mapped[date] = mapped_column(Date, nullable=False)
    resulting_session_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
