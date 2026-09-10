from __future__ import annotations

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("start", ["base", "20260827_0014", "20260830_0015"])
def test_provider_migration_matrix(tmp_path, monkeypatch, start):
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(tmp_path / "runtime"))
    config = Config("backend/alembic.ini")
    assert ScriptDirectory.from_config(config).get_heads() == ["20260910_0016"]
    command.upgrade(config, start)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(Settings())
    columns = {c["name"]: c for c in inspect(engine).get_columns("ai_usage_ledger")}
    assert all(
        columns[n]["nullable"]
        for n in ("prompt_tokens", "cached_prompt_tokens", "completion_tokens", "total_tokens")
    )
    assert "ai_provider_call_bindings" in inspect(engine).get_table_names()
    with engine.connect() as conn:
        triggers = conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        names = {row[0] for row in triggers}
    assert "trg_ai_usage_ledger_no_update" in names
    assert "trg_ai_provider_call_bindings_no_delete" in names
    engine.dispose()
    command.downgrade(config, "20260830_0015")
    command.upgrade(config, "head")


def test_unknown_usage_and_binding_are_durable_append_only(tmp_path, monkeypatch):
    from .test_provenance_migration import _context, _seed_provenance

    config, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,input_fingerprint,started_at) "
                "VALUES ('a','r',1,'STARTED',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "a" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_provider_call_bindings "
                "(attempt_id,run_id,binding_json,reserved_cost,currency,created_at) "
                "VALUES ('a','r','{}',1,'USD',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ai_usage_ledger "
                "(id,run_id,attempt_id,prompt_tokens,cached_prompt_tokens,completion_tokens,"
                "total_tokens,currency,is_estimate,occurred_at) "
                "VALUES ('u','r','a',NULL,NULL,NULL,NULL,'USD',1,CURRENT_TIMESTAMP)"
            )
        )
    for table in ("ai_usage_ledger", "ai_provider_call_bindings"):
        for action in (f"DELETE FROM {table}", f"UPDATE {table} SET currency='CNY'"):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(text(action))
    with pytest.raises(RuntimeError, match="AI_PROVIDER_DOWNGRADE_WOULD_LOSE_PROVENANCE"):
        command.downgrade(config, "20260830_0015")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT prompt_tokens FROM ai_usage_ledger")) is None
        assert connection.scalar(text("SELECT reserved_cost FROM ai_provider_call_bindings")) == 1
    engine.dispose()
