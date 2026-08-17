# ruff: noqa: E501

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

PAPER_TABLES = {
    "paper_accounts",
    "paper_sessions",
    "paper_order_intents",
    "paper_risk_policies",
    "paper_risk_policy_versions",
    "paper_risk_decisions",
    "paper_orders",
    "paper_fills",
    "paper_positions",
    "paper_position_lots",
    "paper_account_snapshots",
    "paper_ledger_entries",
    "paper_audit_events",
    "paper_session_advances",
}

IMMUTABLE_TRIGGERS = {
    "trg_paper_risk_decisions_immutable",
    "trg_paper_risk_decisions_no_delete",
    "trg_paper_fills_immutable",
    "trg_paper_fills_no_delete",
    "trg_paper_ledger_entries_immutable",
    "trg_paper_ledger_entries_no_delete",
    "trg_paper_audit_events_immutable",
    "trg_paper_audit_events_no_delete",
    "trg_paper_risk_policy_versions_immutable",
    "trg_paper_risk_policy_versions_no_delete",
}


def test_paper_tables_exist(engine):
    tables = set(inspect(engine).get_table_names())
    assert tables >= PAPER_TABLES


def test_immutable_triggers_exist(engine):
    with engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'trigger'")
            )
        }
    assert triggers >= IMMUTABLE_TRIGGERS


def test_ledger_entry_immutable(engine):
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO paper_accounts (id,name,status,base_currency,initial_cash,cash,market_value,account_equity,created_at,updated_at) "
                "VALUES ('a','x','ACTIVE','CNY',100,100,0,100,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        session.execute(
            text(
                "INSERT INTO paper_ledger_entries (id,paper_account_id,entry_type,cash_delta,cash_after,created_at) "
                "VALUES ('l1','a','INITIAL_DEPOSIT',100,100,CURRENT_TIMESTAMP)"
            )
        )
        session.commit()
    with Session(engine) as session, pytest.raises(sa.exc.IntegrityError):
        session.execute(
            text("UPDATE paper_ledger_entries SET cash_delta = 200 WHERE id = 'l1'")
        )


def test_risk_policy_version_immutable(engine):
    with Session(engine) as session:
        session.execute(
            text(
                "INSERT INTO paper_accounts (id,name,status,base_currency,initial_cash,cash,market_value,account_equity,created_at,updated_at) "
                "VALUES ('a2','x','ACTIVE','CNY',100,100,0,100,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        session.execute(
            text(
                "INSERT INTO paper_risk_policies (id,paper_account_id,name,status,created_at) "
                "VALUES ('rp1','a2','p','ACTIVE',CURRENT_TIMESTAMP)"
            )
        )
        session.execute(
            text(
                "INSERT INTO paper_risk_policy_versions (id,risk_policy_id,version,max_single_order_notional,max_single_position_weight,max_total_exposure,cash_buffer_ratio,max_daily_loss,max_drawdown,max_open_orders,allowed_security_types_json,policy_fingerprint,created_at) "
                "VALUES ('rpv1','rp1',1,10000,0.5,1.0,0.1,0.05,0.2,10,'[]','f',CURRENT_TIMESTAMP)"
            )
        )
        session.commit()
    with Session(engine) as session, pytest.raises(sa.exc.IntegrityError):
        session.execute(
            text("DELETE FROM paper_risk_policy_versions WHERE id = 'rpv1'")
        )
