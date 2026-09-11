import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from quant_lab.ai.analysis_context import AnalysisContextBuilder
from quant_lab.ai.analysis_contracts import ResearchAnalysisRequest

from .test_ai2_concrete_resolvers import domain_registry as domain_registry
from .test_analysis_context import request
from .test_analysis_orchestration import setup_analysis


def current_request(service, run_id, **changes):
    row = service.analyses.get(run_id)
    payload = service.store.read(json.loads(row.request_artifact_json))
    payload.update(knowledge_cutoff_mode="SERVER_FROZEN_CURRENT", knowledge_cutoff=None)
    payload.update(changes)
    return ResearchAnalysisRequest.model_validate(payload)


def test_server_freeze_real_clock_experiment_and_idempotent_observation(
    domain_registry, tmp_path, monkeypatch
):
    service, run_id, _, repo = setup_analysis(domain_registry, tmp_path)
    loader = domain_registry.get("RESEARCH_EXPERIMENT")._loader.__self__
    loader.clock = lambda: datetime.now(UTC)
    req = current_request(service, run_id, analysis_type="EXPERIMENT_REVIEW", experiment_id="exp1")
    before = datetime.now(UTC)
    row = service.create(req, "server-current")
    context = json.loads(row.context_json)
    cutoff = datetime.fromisoformat(context["resolved_knowledge_cutoff"])
    assert before <= cutoff <= datetime.now(UTC)
    assert cutoff.utcoffset().total_seconds() == 0
    assert context["preflight_gate"]["decision"] == "PROCEED"
    pack = repo.get_evidence_pack(context["evidence_pack_id"])
    assert pack
    from quant_lab.ai.packs import _pack_from_model

    assert all(item.known_at <= cutoff for item in _pack_from_model(pack).items)
    assert context["submitted_request_fingerprint"] == row.request_fingerprint
    assert context["resolved_analysis_input_fingerprint"] != row.request_fingerprint

    def forbidden_observation(*args, **kwargs):
        raise AssertionError("replay must not observe sources")

    monkeypatch.setattr(AnalysisContextBuilder, "build", forbidden_observation)
    assert service.create(req, "server-current").context_json == row.context_json


def test_cutoff_modes_do_not_expand_explicit_or_historical():
    explicit = request()
    assert explicit.knowledge_cutoff_mode == "EXPLICIT"
    assert explicit.knowledge_cutoff == datetime(2026, 9, 11, tzinfo=UTC)
    with pytest.raises(ValidationError):
        request(
            analysis_mode="HISTORICAL_REPLAY",
            knowledge_cutoff_mode="SERVER_FROZEN_CURRENT",
            knowledge_cutoff=None,
        )
    with pytest.raises(ValidationError):
        request(knowledge_cutoff_mode="SERVER_FROZEN_CURRENT")
    with pytest.raises(ValidationError):
        request(knowledge_cutoff=None)


def test_concurrent_create_has_single_observation_epoch(domain_registry, tmp_path, monkeypatch):
    service, run_id, _, _ = setup_analysis(domain_registry, tmp_path)
    req = current_request(service, run_id)
    original = AnalysisContextBuilder.build
    observations = []

    def counted(self, *args, **kwargs):
        observations.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(AnalysisContextBuilder, "build", counted)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.create(req, "concurrent-freeze"), range(2)))
    assert len(observations) == 1
    assert results[0].run_id == results[1].run_id
    assert results[0].context_json == results[1].context_json


def test_source_mutation_cannot_change_frozen_run(domain_registry, tmp_path):
    from sqlalchemy import text

    service, run_id, _, repo = setup_analysis(domain_registry, tmp_path)
    domain_registry.get("RESEARCH_EXPERIMENT")._loader.__self__.clock = lambda: datetime.now(UTC)
    req = current_request(service, run_id, analysis_type="EXPERIMENT_REVIEW", experiment_id="exp1")
    row = service.create(req, "immutable-observation")
    context = json.loads(row.context_json)
    original = repo.get_evidence_pack(context["evidence_pack_id"]).items_json
    with repo.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE research_experiments SET hypothesis='changed after freeze' WHERE id='exp1'"
            )
        )
    assert service.create(req, "immutable-observation").context_json == row.context_json
    assert repo.get_evidence_pack(context["evidence_pack_id"]).items_json == original


@pytest.mark.parametrize("mode", ["CURRENT_RESEARCH", "HISTORICAL_REPLAY"])
def test_explicit_experiment_cutoff_not_expanded(domain_registry, tmp_path, mode):
    service, run_id, _, _ = setup_analysis(domain_registry, tmp_path)
    domain_registry.get("RESEARCH_EXPERIMENT")._loader.__self__.clock = lambda: datetime.now(UTC)
    cutoff = datetime.now(UTC)
    payload = service.store.read(json.loads(service.analyses.get(run_id).request_artifact_json))
    payload.update(
        analysis_type="EXPERIMENT_REVIEW",
        experiment_id="exp1",
        analysis_mode=mode,
        knowledge_cutoff=cutoff,
    )
    row = service.create(ResearchAnalysisRequest.model_validate(payload), "explicit")
    context = json.loads(row.context_json)
    assert datetime.fromisoformat(context["resolved_knowledge_cutoff"]) == cutoff
    assert "FUTURE_KNOWLEDGE" in context["preflight_gate"]["reason_codes"]


def test_server_freeze_does_not_expand_market_cutoff(domain_registry, tmp_path):
    service, run_id, _, _ = setup_analysis(domain_registry, tmp_path)
    row = service.create(
        current_request(service, run_id, market_data_cutoff=datetime(2000, 1, 1, tzinfo=UTC)),
        "old-market",
    )
    context = json.loads(row.context_json)
    assert context["preflight_gate"]["decision"] == "REJECT"
    assert "FUTURE_MARKET_DATA" in context["preflight_gate"]["reason_codes"]
    assert datetime.fromisoformat(context["market_data_cutoff"]).year == 2000


def test_retry_stage2_and_resume_keep_resolved_context(domain_registry, tmp_path, monkeypatch):
    from quant_lab.ai.validation import ValidationResultRecorder

    service, run_id, client, repo = setup_analysis(
        domain_registry, tmp_path, ["schema", "valid", "valid"]
    )
    row = service.create(current_request(service, run_id), "frozen-retries")
    context = row.context_json
    original = ValidationResultRecorder.record

    def crash_after_stage1(self, **kwargs):
        result = original(self, **kwargs)
        if len(client.requests) == 2:
            raise RuntimeError("crash after accepted validation")
        return result

    monkeypatch.setattr(ValidationResultRecorder, "record", crash_after_stage1)
    with pytest.raises(RuntimeError):
        service.execute(row.run_id, "initial")
    monkeypatch.setattr(ValidationResultRecorder, "record", original)
    service.recover()

    def forbidden_observation(*args, **kwargs):
        raise AssertionError("resume must not observe")

    monkeypatch.setattr(domain_registry, "resolve", forbidden_observation)
    result = service.execute(row.run_id, "resume", "RESUME")
    assert result.outcome == "PROCEEDED"
    assert result.context_json == context
    assert len(client.requests) == 3
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from quant_lab.ai.analysis_persistence import AIAnalysisStageBindingModel

    with Session(repo.engine) as session:
        bindings = session.scalars(
            select(AIAnalysisStageBindingModel).where(
                AIAnalysisStageBindingModel.run_id == row.run_id
            )
        ).all()
    assert {
        json.loads(b.binding_json)["resolved_analysis_input_fingerprint"] for b in bindings
    } == {json.loads(context)["resolved_analysis_input_fingerprint"]}
    validated = [e for e in repo.list_trace(row.run_id) if e.event_type.endswith("_VALIDATED")]
    assert len(validated) == 3


def test_interrupted_create_key_never_reobserves(domain_registry, tmp_path, monkeypatch):
    service, run_id, _, _ = setup_analysis(domain_registry, tmp_path)
    req = current_request(service, run_id)

    def crash(*args, **kwargs):
        raise RuntimeError("process interrupted")

    monkeypatch.setattr(AnalysisContextBuilder, "build", crash)
    with pytest.raises(RuntimeError):
        service.create(req, "interrupted")
    with pytest.raises(ValueError, match="ANALYSIS_CONTEXT_INTERRUPTED"):
        service.create(req, "interrupted")


def test_each_approved_source_observed_once_and_new_key_has_new_resolved_identity(
    domain_registry, tmp_path, monkeypatch
):
    from collections import Counter

    from quant_lab.ai.fingerprints import fingerprint_payload

    service, run_id, _, _ = setup_analysis(domain_registry, tmp_path)
    req = current_request(service, run_id, analysis_type="EXPERIMENT_REVIEW", experiment_id="exp1")
    original = domain_registry.resolve
    observed = Counter()

    def counted(selection):
        observed[(selection.source_type, selection.source_id)] += 1
        return original(selection)

    monkeypatch.setattr(domain_registry, "resolve", counted)
    first = service.create(req, "new-a")
    assert max(observed.values()) == 1
    second = service.create(req, "new-b")
    assert (
        first.request_fingerprint
        == second.request_fingerprint
        == fingerprint_payload(req.model_dump(mode="python"))
    )
    a, b = json.loads(first.context_json), json.loads(second.context_json)
    assert a["resolved_analysis_input_fingerprint"] != b["resolved_analysis_input_fingerprint"]
    for context in (a, b):
        expected = context.pop("resolved_analysis_input_fingerprint")
        assert fingerprint_payload(context) == expected


def test_server_freeze_still_filters_future_known_case(domain_registry, tmp_path):
    from sqlalchemy import text

    from quant_lab.ai.retrieval import ResearchCaseDocumentService

    service, run_id, _, repo = setup_analysis(domain_registry, tmp_path)
    with repo.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE ai_research_case_fts USING fts5("
                "document_id UNINDEXED,case_id UNINDEXED,title,summary,"
                "diagnosis,factors,labels_tags)"
            )
        )
    case_id = repo.get_run(run_id).case_id
    ResearchCaseDocumentService(repo).create(
        case_id=case_id,
        title="复核策略表现",
        summary="未来形成的案例",
        diagnosis="仅供记忆",
        success_factors=[],
        failure_factors=[],
        regime_labels=[],
        safe_tags=[],
        universe=[],
        strategy_family=None,
        market_rules_version=None,
    )
    with repo.engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_research_cases SET created_at='2050-01-01 00:00:00' WHERE id=:id"),
            {"id": case_id},
        )
    row = service.create(current_request(service, run_id, requested_case_count=5), "future-case")
    context = json.loads(row.context_json)
    retrieval = repo.get_retrieval_snapshot(context["retrieval_snapshot_id"])
    assert json.loads(retrieval.candidates_json) == []


def test_case_backtracking_reuses_current_epoch_source_observation(
    domain_registry, tmp_path, monkeypatch
):
    from collections import Counter

    from sqlalchemy import text

    from quant_lab.ai.retrieval import ResearchCaseDocumentService

    service, run_id, _, repo = setup_analysis(domain_registry, tmp_path)
    with repo.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE VIRTUAL TABLE ai_research_case_fts USING fts5("
                "document_id UNINDEXED,case_id UNINDEXED,title,summary,"
                "diagnosis,factors,labels_tags)"
            )
        )
    ResearchCaseDocumentService(repo).create(
        case_id=repo.get_run(run_id).case_id,
        title="复核策略表现",
        summary="既有案例",
        diagnosis="仅供记忆",
        success_factors=[],
        failure_factors=[],
        regime_labels=[],
        safe_tags=[],
        universe=[],
        strategy_family=None,
        market_rules_version=None,
    )
    original = domain_registry.resolve
    observed = Counter()

    def counted(selection):
        observed[(selection.source_type, selection.source_id)] += 1
        return original(selection)

    monkeypatch.setattr(domain_registry, "resolve", counted)
    row = service.create(current_request(service, run_id, requested_case_count=5), "cached-memory")
    context = json.loads(row.context_json)
    assert json.loads(repo.get_retrieval_snapshot(context["retrieval_snapshot_id"]).candidates_json)
    assert max(observed.values()) == 1
