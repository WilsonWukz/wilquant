from importlib.util import find_spec

import pytest

from quant_lab.ai import analysis_persistence  # noqa: F401

from .test_provenance_service import _create_run
from .test_provenance_service import provenance as provenance


def test_analysis_persistence_has_explicit_attempt_stage_and_lineage():
    from quant_lab.ai.persistence import AIAnalysisAttemptModel

    columns = AIAnalysisAttemptModel.__table__.columns
    assert "stage" in columns
    assert "parent_attempt_id" in columns
    assert "retry_reason_codes_json" in columns
    assert "validation_feedback_fingerprint" in columns


def test_analysis_repository_exists():
    assert find_spec("quant_lab.ai.analysis_repository") is not None


def _record(provenance):
    from quant_lab.ai.analysis_repository import AnalysisRepository

    run = _create_run(provenance)
    repository = AnalysisRepository(provenance.repository.engine)
    repository.attach(run.id, "create-1", "a" * 64, {"path": "request"}, {})
    return repository, run.id


def test_create_idempotency_conflict_and_stage_lifecycle_separation(provenance):
    repository, run_id = _record(provenance)
    assert repository.find_create("create-1", "a" * 64).run_id == run_id
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_CONFLICT"):
        repository.find_create("create-1", "b" * 64)
    assert repository.get(run_id).progress == "CONTEXT_PREPARED"
    assert repository.get(run_id).outcome is None
    assert provenance.get_run(run_id).status == "CREATED"


def test_execute_owner_and_duplicate_keys_do_not_create_second_epoch(provenance):
    repository, run_id = _record(provenance)
    epoch, fresh = repository.claim(run_id, "execute-1", "c" * 64, "INITIAL")
    assert fresh
    with pytest.raises(ValueError, match="ANALYSIS_IN_PROGRESS"):
        repository.claim(run_id, "execute-2", "c" * 64, "INITIAL")
    with pytest.raises(ValueError, match="IDEMPOTENCY_KEY_CONFLICT"):
        repository.claim(run_id, "execute-1", "d" * 64, "INITIAL")
    repository.checkpoint(
        run_id, epoch.id, progress="TERMINAL", outcome="ABSTAINED", lifecycle="COMPLETED"
    )
    same, fresh = repository.claim(run_id, "execute-1", "c" * 64, "INITIAL")
    assert same.id == epoch.id and not fresh
    assert provenance.get_run(run_id).status == "COMPLETED"
    assert repository.get(run_id).outcome == "ABSTAINED"
    _, fresh = repository.claim(run_id, "execute-new", "c" * 64, "INITIAL")
    assert not fresh


def test_recovery_preserves_stage1_and_requires_new_explicit_epoch(provenance):
    repository, run_id = _record(provenance)
    epoch, _ = repository.claim(run_id, "execute-1", "c" * 64, "INITIAL")
    repository.checkpoint(
        run_id,
        epoch.id,
        progress="STAGE_GATE_DECIDED",
        diagnosis={"sha256": "e" * 64},
        gate={"decision": "PROCEED"},
    )
    repository.recover()
    assert repository.get(run_id).diagnosis_json is not None
    assert repository.get(run_id).active_epoch_id is None
    _, fresh = repository.claim(run_id, "execute-1", "c" * 64, "INITIAL")
    assert not fresh
    second, fresh = repository.claim(run_id, "execute-2", "c" * 64, "RESUME")
    assert fresh and second.id != epoch.id


def test_cancel_without_dispatch_has_no_unknown_cost(provenance):
    repository, run_id = _record(provenance)
    repository.cancel(run_id)
    record = repository.get(run_id)
    assert record.outcome == "CANCELLED"
    assert not record.provider_result_unknown
    assert provenance.get_run(run_id).status == "CANCELLED"
