# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine

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


REVISION_0010 = "20260722_0010"
REVISION_0011 = "20260722_0011"
REVISION_0012 = "20260722_0012"
REVISION_0013 = "20260722_0013"
REVISION_HEAD = "20260910_0016"
SESSION_0013_COLUMNS = {
    "replay_start_date",
    "replay_end_date",
    "execution_config_json",
    "execution_config_fingerprint",
}
ADVANCE_0013_COLUMNS = {"error_code"}


def _column_names(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def test_0013_columns_exist(engine):
    assert _column_names(engine, "paper_sessions") >= SESSION_0013_COLUMNS
    assert _column_names(engine, "paper_session_advances") >= ADVANCE_0013_COLUMNS


def test_empty_database_upgrades_to_0013_head(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    command.upgrade(Config("backend/alembic.ini"), "head")
    engine = create_sqlite_engine(settings)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    assert _column_names(engine, "paper_sessions") >= SESSION_0013_COLUMNS
    engine.dispose()


def test_alembic_has_single_head() -> None:
    heads = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_heads()
    assert heads == [REVISION_HEAD]


def test_head_upgrade_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(settings)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    engine.dispose()


@pytest.mark.parametrize("starting_revision", [REVISION_0010, REVISION_0011, REVISION_0012])
def test_prior_paper_revision_upgrades_to_head(
    tmp_path: Path, monkeypatch, starting_revision: str
) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = Config("backend/alembic.ini")
    command.upgrade(config, starting_revision)
    engine = create_sqlite_engine(settings)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == starting_revision
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    engine.dispose()


def test_0013_downgrades_to_0012_and_upgrades_again(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    engine = create_sqlite_engine(settings)
    command.downgrade(config, REVISION_0012)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_0012
    assert SESSION_0013_COLUMNS.isdisjoint(_column_names(engine, "paper_sessions"))
    assert ADVANCE_0013_COLUMNS.isdisjoint(
        _column_names(engine, "paper_session_advances")
    )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == REVISION_HEAD
    engine.dispose()
