from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine

REVISION_0014 = "20260827_0014"
REVISION_0015 = "20260830_0015"
HISTORY_TABLES = {
    "ai_evidence_packs",
    "ai_validation_results",
    "ai_research_case_documents",
    "ai_retrieval_snapshots",
}


def _context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    return config, create_sqlite_engine(settings)


def _seed_case_and_ai2_rows(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_research_cases "
                "(id,purpose,market,exchange,symbol,instrument_id,asset_type,currency,"
                "timeframe,as_of_utc,market_local_trade_date,bindings_json,fingerprint,"
                "created_by,created_at) VALUES "
                "('case-1','TEST','CN_A_SHARE','SSE','600000','SSE:600000','EQUITY','CNY',"
                "'1D','2024-01-31T00:00:00+00:00','2024-01-31','{}',:fp,'USER',"
                "'2024-02-01T00:00:00+00:00')"
            ),
            {"fp": "1" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_evidence_packs "
                "(id,case_id,temporal_context_json,evidence_context_json,requirements_json,"
                "items_json,policy_version,fingerprint,created_at) VALUES "
                "('pack-1','case-1','{}','{}','{}','[]','v1',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "2" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_research_case_documents "
                "(id,case_id,title,summary,diagnosis,success_factors_json,failure_factors_json,"
                "regime_labels_json,safe_tags_json,universe_json,strategy_family,"
                "market_rules_version,document_fingerprint,created_at) VALUES "
                "('doc-1','case-1','Mean reversion','Stable result','None','[]','[]',"
                "'[]','[]','[]','mean_reversion',NULL,:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "3" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_research_case_fts "
                "(document_id,case_id,title,summary,diagnosis,factors,labels_tags) VALUES "
                "('doc-1','case-1','Mean reversion','Stable result','None','','')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ai_retrieval_snapshots "
                "(id,query_json,policy_version,candidates_json,exclusions_json,fingerprint,"
                "created_at) VALUES ('snap-1','{}','v1','[]','[]',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "4" * 64},
        )


def test_ai2_revision_is_the_single_linear_head() -> None:
    config = Config("backend/alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [REVISION_0015]
    assert script.get_revision(REVISION_0015).down_revision == REVISION_0014


def test_upgrade_creates_four_history_tables_and_derived_fts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    assert set(inspect(engine).get_table_names()) >= HISTORY_TABLES
    with engine.connect() as connection:
        sql = connection.scalar(
            text(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='ai_research_case_fts'"
            )
        )
        assert "VIRTUAL TABLE" in sql.upper()
        assert "fts5" in sql.lower()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0015
    engine.dispose()


def test_history_rows_are_append_only_but_fts_is_disposable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    _seed_case_and_ai2_rows(engine)

    rows = {
        "ai_evidence_packs": "pack-1",
        "ai_research_case_documents": "doc-1",
        "ai_retrieval_snapshots": "snap-1",
    }
    for table_name, row_id in rows.items():
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {table_name} SET id=id WHERE id=:id"), {"id": row_id}
            )
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {table_name} WHERE id=:id"), {"id": row_id})

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_research_case_fts"))
        assert connection.scalar(text("SELECT COUNT(*) FROM ai_research_case_fts")) == 0
    engine.dispose()


def test_ai2_downgrade_upgrade_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, engine = _context(tmp_path, monkeypatch)
    command.downgrade(config, REVISION_0014)
    assert HISTORY_TABLES.isdisjoint(set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT name FROM sqlite_master WHERE name='ai_research_case_fts'")
        ) is None
    command.upgrade(config, "head")
    assert set(inspect(engine).get_table_names()) >= HISTORY_TABLES
    engine.dispose()
