import json

import pytest

from quant_lab.ai import analysis_persistence  # noqa: F401
from quant_lab.ai.analysis_prompts import publish_analysis_prompts
from quant_lab.ai.configuration import AIModelConfigVersionService, PromptTemplateVersionService
from quant_lab.ai.provider_budget import ProviderBudgetPolicy
from quant_lab.ai.repository import AIRepository
from quant_lab.ai_provider_protocol import (
    EndpointProfile,
    ProviderAvailability,
    ProviderCallResult,
    ProviderFailure,
    ProviderUsage,
)

from .test_ai2_concrete_resolvers import domain_registry as domain_registry
from .test_analysis_context import request


class SequencedClient:
    def __init__(self, modes=(), profile=None):
        self.modes = list(modes)
        self.requests = []
        self.on_call = None
        self.profile = profile

    def availability(self):
        return ProviderAvailability(
            profile_id=self.profile.profile_id,
            endpoint_fingerprint=self.profile.fingerprint,
            host_ready=True,
            profile_valid=True,
            credential_store_accessible=True,
            credential_available=True,
        )

    def complete(self, call, policy=None):
        self.requests.append(call)
        if self.on_call:
            self.on_call()
        mode = self.modes.pop(0) if self.modes else "valid"
        if mode == "unknown":
            raise ProviderFailure("PROVIDER_RESULT_UNKNOWN", outcome_unknown=True)
        if mode == "failure":
            raise ProviderFailure("PROVIDER_HTTP_401")
        prompt = json.loads(call.messages[1].content)
        claim_item = next(i for i in prompt["FACT"] if i["field_path"] == "metrics.sharpe")
        claim = {
            "claim_id": "sharpe",
            "claim_type": "FACT",
            "text": "已记录的夏普比率",
            "subject": claim_item["subject"],
            "predicate": "EQ",
            "value": claim_item["value"],
            "unit": claim_item["unit"],
            "evidence_refs": [claim_item["ref_id"]],
        }
        if mode == "bad_fact":
            claim["value"] = "9.99"
        if prompt["DIAGNOSIS"] is None:
            value = {
                "schema_version": "RESEARCH_DIAGNOSIS_V1",
                "analysis_type": "STRATEGY_REVIEW",
                "claims": [claim],
                "observations": ["参考已绑定指标"],
                "risks": [],
                "uncertainties": [],
                "abstention": "无法负责回答" if mode == "abstain" else None,
            }
            if mode == "schema":
                del value["risks"]
        else:
            value = {
                "schema_version": "RESEARCH_RECOMMENDATION_V1",
                "analysis_type": "STRATEGY_REVIEW",
                "summary": "复核策略",
                "claims": [claim],
                "hypotheses": [],
                "uncertainties": [],
                "invalidation_conditions": [],
                "suggested_next_actions": ["REVIEW_STRATEGY"],
                "evidence_refs": [claim_item["ref_id"]],
                "diagnosis_ref": prompt["DIAGNOSIS"]["fingerprint"],
            }
        if mode == "forbidden":
            value["suggested_next_actions"] = ["EXECUTE_LIVE_ORDER"]
        return ProviderCallResult(
            request_id=call.request_id,
            endpoint_fingerprint=call.endpoint_fingerprint,
            model_requested=call.model,
            content=json.dumps(value),
            usage=ProviderUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20),
        )


def setup_analysis(domain_registry, tmp_path, modes=(), max_calls=6):
    from quant_lab.ai.analysis_service import ResearchAnalysisService

    engine = domain_registry.get("DATASET_VERSION")._loader.__self__.engine
    repo = AIRepository(engine)
    first, second = publish_analysis_prompts(PromptTemplateVersionService(repo))
    profile = EndpointProfile(
        profile_id="test",
        base_url="https://example.com/v1",
        model="test",
        credential_ref="wilquant.ai.test",
    )
    model = AIModelConfigVersionService(repo).publish(
        provider_kind="OPENAI_COMPATIBLE",
        provider_id="test",
        base_url_identity=profile.base_url,
        model_identifier="test",
        endpoint_profile_id="test",
        capabilities=profile.capabilities.model_dump(mode="json"),
        parameters={
            "provider_profile": profile.model_dump(mode="json"),
            "budget": ProviderBudgetPolicy(
                max_calls=max_calls, max_input_tokens=131072, max_output_tokens=2048
            ).model_dump(mode="json"),
            "max_output_tokens": 2048,
        },
        actor="USER",
    )
    client = SequencedClient(modes, profile)
    service = ResearchAnalysisService(repo, domain_registry, client, tmp_path)
    row = service.create(
        request(
            model_config_version_id=model.id,
            stage1_prompt_template_version_id=first.id,
            stage2_prompt_template_version_id=second.id,
        ),
        "create",
    )
    return service, row.run_id, client, repo


def test_two_stages_one_run_two_validations(domain_registry, tmp_path):
    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    result = service.execute(run_id, "execute")
    assert result.outcome == "PROCEEDED"
    assert result.progress == "TERMINAL"
    assert len(client.requests) == 2
    assert result.diagnosis_json and result.recommendation_json
    attempts = repo.list_attempts(run_id)
    assert [a.stage for a in attempts] == ["STAGE_1_DIAGNOSIS", "STAGE_2_RECOMMENDATION"]
    assert len(repo.list_validation_results(run_id)) == 2
    events = {event.event_type for event in repo.list_trace(run_id)}
    assert {
        "CONTEXT_BUILT",
        "EVIDENCE_FROZEN",
        "CASES_RETRIEVED",
        "STAGE1_STARTED",
        "STAGE1_ATTEMPT",
        "STAGE1_VALIDATED",
        "STAGE_GATE_DECIDED",
        "STAGE2_STARTED",
        "STAGE2_ATTEMPT",
        "STAGE2_VALIDATED",
        "ANALYSIS_COMPLETED",
    } <= events
    service.execute(run_id, "execute")
    service.execute(run_id, "new-key")
    assert len(client.requests) == 2


def test_missing_context_artifact_rejects_without_leaving_active_epoch(domain_registry, tmp_path):
    service, run_id, client, _repo = setup_analysis(domain_registry, tmp_path)
    metadata = json.loads(service.analyses.get(run_id).context_json)["context_artifact"]
    artifact = (tmp_path / metadata["path"]).resolve()
    assert artifact.is_relative_to(tmp_path.resolve())
    artifact.unlink()
    result = service.execute(run_id, "missing-artifact")
    assert result.outcome == "REJECTED"
    assert result.active_epoch_id is None
    assert client.requests == []


@pytest.mark.parametrize(
    "modes,outcome,count",
    [
        (["abstain"], "ABSTAINED", 1),
        (["failure"], "PROVIDER_FAILED", 1),
        (["valid", "bad_fact"], "REJECTED", 2),
        (["schema", "valid", "valid"], "PROCEEDED", 3),
        (["unknown"], "PROVIDER_RESULT_UNKNOWN", 1),
    ],
)
def test_gate_retry_and_failures(domain_registry, tmp_path, modes, outcome, count):
    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path, modes)
    result = service.execute(run_id, "execute")
    assert result.outcome == outcome
    assert len(client.requests) == count
    if modes[0] == "schema":
        attempts = repo.list_attempts(run_id)
        assert attempts[1].parent_attempt_id == attempts[0].id
        assert attempts[1].validation_feedback_fingerprint


def test_shared_budget_blocks_second_stage_and_retains_diagnosis(domain_registry, tmp_path):
    service, run_id, client, _repo = setup_analysis(domain_registry, tmp_path, max_calls=1)
    result = service.execute(run_id, "execute")
    assert result.outcome == "BUDGET_BLOCKED"
    assert result.diagnosis_json and not result.recommendation_json
    assert len(client.requests) == 1


def test_cancel_inflight_retains_unknown_and_never_calls_stage2(domain_registry, tmp_path):
    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    client.on_call = lambda: service.cancel(run_id)
    result = service.execute(run_id, "execute")
    assert result.outcome == "CANCELLED"
    assert result.provider_result_unknown
    assert repo.list_attempts(run_id)[0].status == "ABANDONED"
    assert len(client.requests) == 1


@pytest.mark.parametrize("crash_stage", [1, 2])
def test_restart_after_validation_never_reinvokes_completed_attempt(
    domain_registry, tmp_path, monkeypatch, crash_stage
):
    from quant_lab.ai.validation import ValidationResultRecorder

    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    original = ValidationResultRecorder.record

    def crash_after_record(self, **kwargs):
        result = original(self, **kwargs)
        if len(client.requests) == crash_stage:
            raise RuntimeError("simulated process crash")
        return result

    monkeypatch.setattr(ValidationResultRecorder, "record", crash_after_record)
    with pytest.raises(RuntimeError):
        service.execute(run_id, "first")
    monkeypatch.setattr(ValidationResultRecorder, "record", original)
    service.recover()
    if crash_stage == 2:

        def offline_host():
            raise ProviderFailure("PROVIDER_HOST_UNAVAILABLE")

        monkeypatch.setattr(client, "availability", offline_host)
    result = service.execute(run_id, "resume", "RESUME")
    assert result.outcome == "PROCEEDED"
    assert len(client.requests) == 2
    assert len(repo.list_validation_results(run_id)) == 2


def test_restart_after_rejected_validation_does_not_retry(domain_registry, tmp_path, monkeypatch):
    from quant_lab.ai.validation import ValidationResultRecorder

    service, run_id, client, _repo = setup_analysis(domain_registry, tmp_path, ["bad_fact"])
    original = ValidationResultRecorder.record

    def crash_after_record(self, **kwargs):
        original(self, **kwargs)
        raise RuntimeError("simulated process crash")

    monkeypatch.setattr(ValidationResultRecorder, "record", crash_after_record)
    with pytest.raises(RuntimeError):
        service.execute(run_id, "first")
    monkeypatch.setattr(ValidationResultRecorder, "record", original)
    service.recover()
    assert service.execute(run_id, "resume", "RESUME").outcome == "REJECTED"
    assert len(client.requests) == 1


def test_unknown_requires_new_key_and_explicit_intent(domain_registry, tmp_path):
    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path, ["valid", "unknown"])
    first = service.execute(run_id, "first")
    diagnosis = first.diagnosis_json
    assert first.outcome == "PROVIDER_RESULT_UNKNOWN"
    service.execute(run_id, "first")
    with pytest.raises(ValueError, match="PROVIDER_UNKNOWN_CONFIRMATION_REQUIRED"):
        service.execute(run_id, "resume", "RESUME")
    result = service.execute(run_id, "confirm", "RETRY_UNKNOWN")
    assert result.outcome == "PROCEEDED"
    assert result.diagnosis_json == diagnosis
    assert len(client.requests) == 3
    attempts = repo.list_attempts(run_id)
    assert attempts[1].status == "ABANDONED"
    assert attempts[2].parent_attempt_id == attempts[1].id
    assert attempts[2].retry_reason_codes_json != "[]"


def test_startup_recovery_preserves_ai4_completed_stage(domain_registry, tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from quant_lab.ai.analysis_execution import TwoStageResearchExecution
    from quant_lab.ai.provenance import AIProvenanceService

    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    original = TwoStageResearchExecution._stage

    def crash_before_stage2(self, run_id, epoch, number, *args):
        if number == 2:
            raise RuntimeError("simulated process crash")
        return original(self, run_id, epoch, number, *args)

    monkeypatch.setattr(TwoStageResearchExecution, "_stage", crash_before_stage2)
    with pytest.raises(RuntimeError):
        service.execute(run_id, "first")
    monkeypatch.setattr(TwoStageResearchExecution, "_stage", original)
    AIProvenanceService(repo).recover_incomplete_runs(datetime.now(UTC))
    assert repo.get_run(run_id).status == "RUNNING"
    assert service.analyses.get(run_id).active_epoch_id is None
    assert len(client.requests) == 1
    assert service.execute(run_id, "resume", "RESUME").outcome == "PROCEEDED"
    assert len(client.requests) == 2


def test_concurrent_execute_has_one_owner_and_cancel_stops_next_stage(domain_registry, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    entered, release = Event(), Event()

    def block_call():
        entered.set()
        assert release.wait(10)

    client.on_call = block_call
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.execute, run_id, "owner")
        try:
            assert entered.wait(10)
            with pytest.raises(ValueError, match="ANALYSIS_IN_PROGRESS"):
                service.execute(run_id, "other-owner")
            service.cancel(run_id)
        finally:
            release.set()
        assert future.result(timeout=10).outcome == "CANCELLED"
    assert len(client.requests) == 1
    assert repo.list_attempts(run_id)[0].status == "ABANDONED"


def test_concurrent_create_returns_same_run(domain_registry, tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from quant_lab.ai.analysis_contracts import ResearchAnalysisRequest

    service, run_id, client, _repo = setup_analysis(domain_registry, tmp_path)
    original = ResearchAnalysisRequest.model_validate(
        service.store.read(json.loads(service.analyses.get(run_id).request_artifact_json))
    )
    changed = original.model_copy(update={"research_question": "独立并发创建测试"})
    barrier = Barrier(2)

    def create():
        barrier.wait(10)
        return service.create(changed, "concurrent-create").run_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(create)
        assert first.result(timeout=20) == second.result(timeout=20)
    assert not client.requests


@pytest.mark.parametrize(
    "modes,code,count",
    [
        (["schema", "bad_fact"], "IMMUTABLE_FACT_DRIFT", 2),
        (["forbidden"], "FORBIDDEN_AI_AUTHORITY", 1),
        (["valid", "forbidden"], "FORBIDDEN_AI_AUTHORITY", 2),
    ],
)
def test_adversarial_outputs_never_accepted_or_retried(
    domain_registry, tmp_path, modes, code, count
):
    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path, modes)
    result = service.execute(run_id, "execute")
    assert result.outcome == "REJECTED"
    assert len(client.requests) == count
    assert not result.recommendation_json
    assert any(code in r.findings_json for r in repo.list_validation_results(run_id))


@pytest.mark.parametrize("question", ["涨跌停规则如何影响策略", "T+1 是否允许卖出"])
def test_required_missing_market_rules_blocks_all_provider_calls(
    domain_registry, tmp_path, question
):
    from quant_lab.ai.analysis_contracts import ResearchAnalysisRequest

    service, run_id, client, _repo = setup_analysis(domain_registry, tmp_path)
    original = ResearchAnalysisRequest.model_validate(
        service.store.read(json.loads(service.analyses.get(run_id).request_artifact_json))
    )
    row = service.create(
        original.model_copy(update={"research_question": question}), "rules-request"
    )
    result = service.execute(row.run_id, "execute")
    assert result.outcome == "WAIT_FOR_EVIDENCE"
    assert not client.requests


def test_dispatch_rechecks_durable_stage_gate(domain_registry, tmp_path, monkeypatch):
    from sqlalchemy.orm import Session

    from quant_lab.ai.analysis_persistence import AIAnalysisOrchestrationModel
    from quant_lab.ai.provider_execution import AIProviderExecutionService

    service, run_id, client, repo = setup_analysis(domain_registry, tmp_path)
    reserve = AIProviderExecutionService._reserve

    def inject_gate_fault(self, context, messages):
        if len(client.requests) == 1:
            with Session(repo.engine) as session:
                row = session.get(AIAnalysisOrchestrationModel, run_id)
                gate = json.loads(row.gate_json)
                gate["decision"] = "ABSTAIN"
                row.gate_json = json.dumps(gate)
                session.commit()
        return reserve(self, context, messages)

    monkeypatch.setattr(AIProviderExecutionService, "_reserve", inject_gate_fault)
    assert service.execute(run_id, "execute").outcome == "REJECTED"
    assert len(client.requests) == 1
    assert all(a.status != "STARTED" for a in repo.list_attempts(run_id))
