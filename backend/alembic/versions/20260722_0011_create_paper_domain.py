
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260722_0011"
down_revision: str | None = "20260722_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _immutable_triggers(table: str, message: str) -> None:
    op.execute(
        f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{message}'); END;"
    )


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("base_currency", sa.String(8), nullable=False),
        sa.Column("initial_cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("account_equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("initial_cash > 0", name="ck_paper_account_initial_cash_positive"),
        sa.CheckConstraint("cash >= 0", name="ck_paper_account_cash_nonnegative"),
        sa.CheckConstraint("market_value >= 0", name="ck_paper_account_market_value_nonnegative"),
        sa.CheckConstraint("account_equity >= 0", name="ck_paper_account_equity_nonnegative"),
    )
    op.create_table(
        "paper_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "market_data_profile_id",
            sa.String(36),
            sa.ForeignKey("market_data_profiles.profile_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("market_data_snapshot_json", sa.Text(), nullable=False),
        sa.Column("market_data_snapshot_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "strategy_version_id",
            sa.String(36),
            sa.ForeignKey("strategy_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_session_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_paper_session_version_positive"),
    )
    op.create_table(
        "paper_order_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=True),
        sa.Column("instrument_id", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(32), nullable=False),
        sa.Column("limit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("signal_session_date", sa.Date(), nullable=False),
        sa.Column("intended_execution_session", sa.Date(), nullable=False),
        sa.Column(
            "strategy_version_id",
            sa.String(36),
            sa.ForeignKey("strategy_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("paper_session_id", "idempotency_key"),
    )
    op.create_table(
        "paper_risk_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_risk_policy_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "risk_policy_id",
            sa.String(36),
            sa.ForeignKey("paper_risk_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("max_single_order_notional", sa.Numeric(20, 8), nullable=False),
        sa.Column("max_single_position_weight", sa.Numeric(10, 6), nullable=False),
        sa.Column("max_total_exposure", sa.Numeric(10, 6), nullable=False),
        sa.Column("cash_buffer_ratio", sa.Numeric(10, 6), nullable=False),
        sa.Column("max_daily_loss", sa.Numeric(10, 6), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(10, 6), nullable=False),
        sa.Column("max_open_orders", sa.Integer(), nullable=False),
        sa.Column("allowed_security_types_json", sa.Text(), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("risk_policy_id", "version"),
    )
    op.create_table(
        "paper_risk_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "order_intent_id",
            sa.String(36),
            sa.ForeignKey("paper_order_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_codes_json", sa.Text(), nullable=False),
        sa.Column(
            "risk_policy_id",
            sa.String(36),
            sa.ForeignKey("paper_risk_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "risk_policy_version_id",
            sa.String(36),
            sa.ForeignKey("paper_risk_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("risk_policy_version", sa.Integer(), nullable=False),
        sa.Column("account_snapshot_json", sa.Text(), nullable=False),
        sa.Column("position_snapshot_json", sa.Text(), nullable=False),
        sa.Column("market_context_json", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_order_id", sa.String(64), nullable=False),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_intent_id",
            sa.String(36),
            sa.ForeignKey("paper_order_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "risk_decision_id",
            sa.String(36),
            sa.ForeignKey("paper_risk_decisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.Column("accepted_quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(32), nullable=False),
        sa.Column("limit_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("submitted_session_date", sa.Date(), nullable=True),
        sa.Column("execution_session_date", sa.Date(), nullable=True),
        sa.Column("reject_reason", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_order_id"),
    )
    op.create_table(
        "paper_fills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_order_id",
            sa.String(36),
            sa.ForeignKey("paper_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("raw_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("slippage", sa.Numeric(20, 8), nullable=False),
        sa.Column("fill_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("commission", sa.Numeric(20, 8), nullable=False),
        sa.Column("stamp_tax", sa.Numeric(20, 8), nullable=False),
        sa.Column("transfer_fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("total_fee", sa.Numeric(20, 8), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(32), nullable=False),
        sa.Column("total_quantity", sa.Integer(), nullable=False),
        sa.Column("sellable_quantity", sa.Integer(), nullable=False),
        sa.Column("average_cost", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("paper_account_id", "instrument_id"),
    )
    op.create_table(
        "paper_position_lots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_position_id",
            sa.String(36),
            sa.ForeignKey("paper_positions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("instrument_id", sa.String(32), nullable=False),
        sa.Column("acquired_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("remaining_quantity", sa.Integer(), nullable=False),
        sa.Column("cost_price", sa.Numeric(20, 8), nullable=False),
        sa.Column("sellable_from_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "remaining_quantity >= 0 AND remaining_quantity <= quantity",
            name="ck_paper_lot_remaining_range",
        ),
    )
    op.create_table(
        "paper_account_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("cash", sa.Numeric(20, 8), nullable=False),
        sa.Column("market_value", sa.Numeric(20, 8), nullable=False),
        sa.Column("equity", sa.Numeric(20, 8), nullable=False),
        sa.Column("gross_exposure", sa.Numeric(10, 6), nullable=False),
        sa.Column("daily_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("cumulative_pnl", sa.Numeric(20, 8), nullable=False),
        sa.Column("drawdown", sa.Numeric(10, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("paper_session_id", "session_date"),
    )
    op.create_table(
        "paper_ledger_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "paper_fill_id",
            sa.String(36),
            sa.ForeignKey("paper_fills.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("cash_delta", sa.Numeric(20, 8), nullable=False),
        sa.Column("cash_after", sa.Numeric(20, 8), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_account_id",
            sa.String(36),
            sa.ForeignKey("paper_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_session_advances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "paper_session_id",
            sa.String(36),
            sa.ForeignKey("paper_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("expected_session_date", sa.Date(), nullable=False),
        sa.Column("resulting_session_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("paper_session_id", "idempotency_key"),
    )

    _immutable_triggers("paper_risk_decisions", "paper risk decision immutable")
    _immutable_triggers("paper_fills", "paper fill immutable")
    _immutable_triggers("paper_ledger_entries", "paper ledger entry immutable")
    _immutable_triggers("paper_audit_events", "paper audit event immutable")
    _immutable_triggers("paper_risk_policy_versions", "paper risk policy version immutable")


def downgrade() -> None:
    op.drop_table("paper_session_advances")
    op.drop_table("paper_audit_events")
    op.drop_table("paper_ledger_entries")
    op.drop_table("paper_account_snapshots")
    op.drop_table("paper_position_lots")
    op.drop_table("paper_positions")
    op.drop_table("paper_fills")
    op.drop_table("paper_orders")
    op.drop_table("paper_risk_decisions")
    op.drop_table("paper_risk_policy_versions")
    op.drop_table("paper_risk_policies")
    op.drop_table("paper_order_intents")
    op.drop_table("paper_sessions")
    op.drop_table("paper_accounts")
