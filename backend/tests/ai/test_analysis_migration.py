import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from quant_lab.core.config import Settings
from quant_lab.db.sqlite import create_sqlite_engine


@pytest.mark.parametrize("start", ["base", "20260830_0015", "20260910_0016"])
def test_analysis_migration_matrix_and_history(tmp_path, monkeypatch, start):
    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_SQLITE_PATH", str(tmp_path / "audit.db"))
    config = Config("backend/alembic.ini")
    assert ScriptDirectory.from_config(config).get_heads() == ["20260911_0017"]
    command.upgrade(config, start)
    command.upgrade(config, "head")
    engine = create_sqlite_engine(Settings())
    columns = {c["name"] for c in inspect(engine).get_columns("ai_analysis_attempts")}
    assert {
        "stage",
        "parent_attempt_id",
        "retry_reason_codes_json",
        "validation_feedback_fingerprint",
    } <= columns
    engine.dispose()
    command.downgrade(config, "20260910_0016")
    command.upgrade(config, "head")


def test_analysis_identity_and_stage_are_immutable_in_database(tmp_path, monkeypatch):
    from .test_provenance_migration import _context, _seed_provenance

    config, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,stage,input_fingerprint,started_at) "
                "VALUES ('a','r',1,'STARTED','STAGE_1_DIAGNOSIS',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "a" * 64},
        )
    for statement in [
        "UPDATE ai_analysis_attempts SET stage='STAGE_2_RECOMMENDATION'",
        "UPDATE ai_analysis_attempts SET retry_reason_codes_json='[]'",
    ]:
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(text(statement))
    with pytest.raises(RuntimeError, match="AI_ANALYSIS_DOWNGRADE_WOULD_LOSE_PROVENANCE"):
        command.downgrade(config, "20260910_0016")
    engine.dispose()


def test_two_stage_runs_against_migrated_database_triggers(tmp_path, monkeypatch):
    from .test_ai2_concrete_resolvers import domain_registry
    from .test_analysis_orchestration import setup_analysis

    monkeypatch.setenv("QUANT_LAB_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_RUNTIME_ROOT", str(tmp_path))
    monkeypatch.setenv("QUANT_LAB_SQLITE_PATH", str(tmp_path / "domain.db"))
    command.upgrade(Config("backend/alembic.ini"), "head")
    registry_generator = domain_registry.__wrapped__(tmp_path)
    registry = next(registry_generator)
    service, run_id, client, repo = setup_analysis(registry, tmp_path)
    with pytest.raises(IntegrityError, match="validation linkage"), repo.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE ai_analysis_orchestrations SET diagnosis_json=:metadata WHERE run_id=:run"
            ),
            {
                "metadata": '{"validation_result_id":"missing","attempt_id":"missing"}',
                "run": run_id,
            },
        )
    assert service.execute(run_id, "execute").outcome == "PROCEEDED"
    assert len(client.requests) == 2
    with repo.engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%analysis%'")
        ).all()
    assert rows
    for statement in [
        "DELETE FROM ai_analysis_stage_bindings",
        "UPDATE ai_analysis_stage_bindings SET fingerprint='x'",
        "UPDATE ai_analysis_orchestrations SET diagnosis_json=NULL",
    ]:
        with pytest.raises(IntegrityError), repo.engine.begin() as conn:
            conn.execute(text(statement))
    next(registry_generator, None)


def test_stage_binding_cannot_attach_without_matching_active_owner(tmp_path, monkeypatch):
    from .test_provenance_migration import _context, _seed_provenance

    _, engine = _context(tmp_path, monkeypatch)
    _seed_provenance(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ai_analysis_attempts "
                "(id,run_id,attempt_number,status,stage,input_fingerprint,started_at) "
                "VALUES ('a','r',1,'STARTED','STAGE_1_DIAGNOSIS',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "a" * 64},
        )
        conn.execute(
            text(
                "INSERT INTO ai_analysis_execution_epochs "
                "(id,run_id,idempotency_key,payload_fingerprint,intent,status,created_at) "
                "VALUES ('e','r','e',:fp,'INITIAL','ACTIVE',CURRENT_TIMESTAMP)"
            ),
            {"fp": "a" * 64},
        )
    with pytest.raises(IntegrityError, match="binding relationship"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO ai_analysis_stage_bindings "
                "VALUES ('a','r','e','{}',:fp,CURRENT_TIMESTAMP)"
            ),
            {"fp": "a" * 64},
        )
    engine.dispose()
