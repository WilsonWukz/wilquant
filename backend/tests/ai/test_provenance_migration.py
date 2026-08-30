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

REVISION_0013 = "20260722_0013"
REVISION_0014 = "20260827_0014"
REVISION_HEAD = "20260830_0015"
AI_TABLES = {
    "ai_prompt_template_versions",
    "ai_model_config_versions",
    "ai_research_cases",
    "ai_evidence_refs",
    "ai_analysis_runs",
    "ai_analysis_attempts",
    "ai_analysis_trace_events",
    "ai_usage_ledger",
}


def _context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = Settings(project_root=tmp_path, runtime_root=tmp_path / "runtime")
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(settings.runtime_root))
    config = Config("backend/alembic.ini")
    command.upgrade(config, "head")
    return config, create_sqlite_engine(settings)


def _seed_provenance(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_prompt_template_versions "
                "(id,template_name,stage,schema_version,content,content_sha256,"
                "variable_contract_json,variable_contract_sha256,validator_policy_version,"
                "fingerprint,status,created_by,created_at) VALUES "
                "('p','prompt','DIAGNOSIS','1','x',:a,'{}',:b,'v1',:c,'PUBLISHED','USER',CURRENT_TIMESTAMP)"
            ),
            {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_model_config_versions "
                "(id,provider_kind,provider_id,base_url_identity,model_identifier,"
                "endpoint_profile_id,capabilities_json,parameters_json,fingerprint,"
                "created_by,created_at) VALUES "
                "('m','FAKE','fake','local','fake-v1','fake','{}','{}',:f,'USER',CURRENT_TIMESTAMP)"
            ),
            {"f": "d" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_research_cases "
                "(id,purpose,market,exchange,symbol,instrument_id,asset_type,currency,"
                "timeframe,as_of_utc,market_local_trade_date,bindings_json,fingerprint,"
                "created_by,created_at) VALUES "
                "('c','TEST','CN_A_SHARE','SSE','600000','600000.XSHG','EQUITY','CNY',"
                "'1D',CURRENT_TIMESTAMP,'2026-08-27','{}',:f,'USER',CURRENT_TIMESTAMP)"
            ),
            {"f": "e" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_runs "
                "(id,case_id,stage,status,prompt_template_version_id,model_config_version_id,"
                "case_fingerprint,prompt_template_fingerprint,resolved_prompt_fingerprint,"
                "model_config_fingerprint,validator_policy_version,validator_policy_fingerprint,"
                "created_at) VALUES "
                "('r','c','DIAGNOSIS','CREATED','p','m',:a,:b,:c,:d,'v1',:e,CURRENT_TIMESTAMP)"
            ),
            {
                "a": "e" * 64,
                "b": "c" * 64,
                "c": "f" * 64,
                "d": "d" * 64,
                "e": "1" * 64,
            },
        )


def test_alembic_has_single_ai_provenance_head() -> None:
    heads = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_heads()
    assert heads == [REVISION_HEAD]


def test_empty_database_upgrades_to_ai_provenance_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    assert AI_TABLES.issubset(set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert version == REVISION_HEAD
    engine.dispose()


def test_immutable_rows_and_run_identity_are_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            text("UPDATE ai_prompt_template_versions SET content='changed' WHERE id='p'")
        )
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_model_config_versions WHERE id='m'"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE ai_research_cases SET symbol='AAPL' WHERE id='c'"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE ai_analysis_runs SET case_id='other' WHERE id='r'"))
    engine.dispose()


def test_all_append_only_audit_rows_reject_update_and_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_evidence_refs "
                "(id,case_id,evidence_type,source_entity_type,source_entity_id,"
                "source_version_id,content_sha256,locator_json,effective_at,known_at,"
                "captured_at,market,instrument_id,currency,temporal_status,integrity_status,"
                "fingerprint,created_at) VALUES "
                "('e','c','MARKET_DATA','dataset','dataset-1','v1',:content,'{}',"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'CN_A_SHARE',"
                "'600000.XSHG','CNY','VALID','VERIFIED',:fingerprint,CURRENT_TIMESTAMP)"
            ),
            {"content": "7" * 64, "fingerprint": "8" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,input_fingerprint,started_at) "
                "VALUES ('a','r',1,'STARTED',:fingerprint,CURRENT_TIMESTAMP)"
            ),
            {"fingerprint": "9" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_trace_events "
                "(id,run_id,sequence,event_type,payload_json,payload_fingerprint,occurred_at) "
                "VALUES ('t','r',1,'RUN_CREATED','{}',:fingerprint,CURRENT_TIMESTAMP)"
            ),
            {"fingerprint": "a" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_usage_ledger "
                "(id,run_id,attempt_id,prompt_tokens,cached_prompt_tokens,completion_tokens,"
                "total_tokens,currency,is_estimate,occurred_at) "
                "VALUES ('u','r','a',1,0,1,2,'USD',0,CURRENT_TIMESTAMP)"
            )
        )

    immutable_rows = {
        "ai_prompt_template_versions": "p",
        "ai_model_config_versions": "m",
        "ai_research_cases": "c",
        "ai_evidence_refs": "e",
        "ai_analysis_trace_events": "t",
        "ai_usage_ledger": "u",
    }
    for table_name, row_id in immutable_rows.items():
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(text(f"UPDATE {table_name} SET id=id WHERE id=:id"), {"id": row_id})
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {table_name} WHERE id=:id"), {"id": row_id})
    engine.dispose()


def test_run_and_attempt_can_finalize_once_then_become_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ai_analysis_runs SET status='RUNNING',input_envelope_fingerprint=:f,"
                "started_at=CURRENT_TIMESTAMP WHERE id='r'"
            ),
            {"f": "2" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,input_fingerprint,started_at) "
                "VALUES ('a','r',1,'STARTED',:f,CURRENT_TIMESTAMP)"
            ),
            {"f": "3" * 64},
        )
        connection.execute(
            text(
                "UPDATE ai_analysis_attempts SET status='COMPLETED',output_fingerprint=:f,"
                "latency_ms=1,finish_reason='stop',completed_at=CURRENT_TIMESTAMP WHERE id='a'"
            ),
            {"f": "4" * 64},
        )
        connection.execute(
            text(
                "UPDATE ai_analysis_runs SET status='COMPLETED',raw_response_artifact_sha256=:r,"
                "normalized_output_fingerprint=:n,completed_at=CURRENT_TIMESTAMP WHERE id='r'"
            ),
            {"r": "5" * 64, "n": "6" * 64},
        )

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE ai_analysis_attempts SET latency_ms=2 WHERE id='a'"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_analysis_attempts WHERE id='a'"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("UPDATE ai_analysis_runs SET failure_code='changed' WHERE id='r'"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_analysis_runs WHERE id='r'"))
    engine.dispose()


def test_ai_provenance_downgrades_and_upgrades_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, engine = _context(tmp_path, monkeypatch)
    command.downgrade(config, REVISION_0013)
    assert AI_TABLES.isdisjoint(set(inspect(engine).get_table_names()))
    command.upgrade(config, "head")
    assert AI_TABLES.issubset(set(inspect(engine).get_table_names()))
    engine.dispose()
