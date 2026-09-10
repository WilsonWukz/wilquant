from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quant_lab.ai.provenance import AIUsageInput

from .test_provenance_service import _create_run
from .test_provenance_service import provenance as provenance


@pytest.mark.parametrize("tokens", [(None, None, None, None), (10, None, 2, 12), (0, 0, 0, 0)])
def test_nullable_usage_preserves_unknown_and_explicit_zero(provenance, tokens):
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "a" * 64)
    usage = provenance.append_usage(attempt.id, AIUsageInput(*tokens, None, None, "USD", True))
    assert (
        usage.prompt_tokens,
        usage.cached_prompt_tokens,
        usage.completion_tokens,
        usage.total_tokens,
    ) == tokens


def test_recovery_marks_unknown_not_known_failure(provenance):
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "a" * 64)
    provenance.recover_incomplete_runs(datetime.now(UTC))
    recovered = provenance.get_attempt(attempt.id)
    assert recovered.status == "ABANDONED"
    assert recovered.failure_code == "PROVIDER_RESULT_UNKNOWN"


@pytest.mark.parametrize("terminal", ["CANCELLED", "FAILED"])
def test_recovery_finds_started_attempt_in_terminal_run(provenance, terminal):
    run = _create_run(provenance)
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "a" * 64)
    if terminal == "CANCELLED":
        provenance.cancel_run(run.id)
    else:
        provenance.fail_run(run.id, "TEST", "test")
    provenance.recover_incomplete_runs(datetime.now(UTC))
    assert provenance.get_attempt(attempt.id).status == "ABANDONED"
    assert provenance.get_run(run.id).status == terminal


def test_execution_service_exists():
    from importlib.util import find_spec

    assert find_spec("quant_lab.ai.provider_execution") is not None


@pytest.fixture
def execution_context(provenance, tmp_path):
    return make_execution_context(provenance, tmp_path)


def make_execution_context(provenance, tmp_path, profile=None, budget=None, call_policy=None):
    from uuid import uuid4

    from sqlalchemy.orm import Session

    from quant_lab.ai.configuration import AIModelConfigVersionService
    from quant_lab.ai.fingerprints import fingerprint_payload
    from quant_lab.ai.persistence import AIEvidencePackModel
    from quant_lab.ai.provider_budget import ProviderBudgetPolicy
    from quant_lab.ai.provider_execution import AuthorizedProviderContext
    from quant_lab.ai_provider_protocol import CallPolicy, EndpointProfile, ProviderMessage

    profile = profile or EndpointProfile(
        profile_id="test",
        base_url="https://example.com/v1",
        model="test",
        credential_ref="wilquant.ai.test",
    )
    budget = budget or ProviderBudgetPolicy(
        input_cost_per_1m_tokens="1", output_cost_per_1m_tokens="2"
    )
    model = AIModelConfigVersionService(provenance.repository).publish(
        provider_kind="OPENAI_COMPATIBLE",
        provider_id="test",
        base_url_identity=profile.base_url,
        model_identifier=profile.model,
        endpoint_profile_id=profile.profile_id,
        capabilities=profile.capabilities.model_dump(mode="json"),
        parameters={
            "provider_profile": profile.model_dump(mode="json"),
            "budget": budget.model_dump(mode="json"),
            "max_output_tokens": 20,
            "call_policy": (call_policy or CallPolicy()).model_dump(mode="json"),
        },
        actor="USER",
    )
    messages = [ProviderMessage(role="user", content="Return JSON.")]
    run = provenance.create_run(
        case_id=provenance.test_case_id,
        stage="DIAGNOSIS",
        prompt_template_version_id=provenance.test_prompt_id,
        model_config_version_id=model.id,
        resolved_prompt_fingerprint=fingerprint_payload([m.model_dump() for m in messages]),
        validator_policy_version="v1",
        validator_policy_fingerprint="b" * 64,
    )
    provenance.start_run(run.id, "f" * 64)
    attempt = provenance.start_attempt(run.id, "a" * 64)
    pack_id = str(uuid4())
    with Session(provenance.repository.engine) as session:
        session.add(
            AIEvidencePackModel(
                id=pack_id,
                case_id=run.case_id,
                temporal_context_json="{}",
                evidence_context_json="{}",
                requirements_json="{}",
                items_json="[]",
                policy_version="v1",
                fingerprint="c" * 64,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    context = AuthorizedProviderContext(
        attempt_id=attempt.id,
        evidence_pack_id=pack_id,
        evidence_pack_fingerprint="c" * 64,
        gate_decision="PROCEED",
        gate_fingerprint="d" * 64,
    )
    return provenance, profile, context, messages, tmp_path


@pytest.mark.parametrize(
    "failure,unknown,status",
    [
        (None, False, "COMPLETED"),
        ("PROVIDER_AUTH_FAILED", False, "FAILED"),
        ("PROVIDER_TIMEOUT", True, "ABANDONED"),
    ],
)
def test_attempt_invocation_persistence_and_failure_semantics(
    execution_context, failure, unknown, status
):
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from quant_lab.ai.persistence import AIProviderCallBindingModel, AIValidationResultModel
    from quant_lab.ai.provider_execution import AIProviderExecutionService
    from quant_lab.ai_provider_protocol import ProviderCallResult, ProviderFailure, ProviderUsage

    provenance, profile, context, messages, root = execution_context
    calls = []

    class Client:
        def complete(self, request, policy=None):
            with Session(provenance.repository.engine) as session:
                binding = session.get(AIProviderCallBindingModel, request.request_id)
                assert binding is not None and binding.reserved_cost > 0
            calls.append(request.request_id)
            if failure:
                raise ProviderFailure(failure, outcome_unknown=unknown)
            return ProviderCallResult(
                request_id=request.request_id,
                endpoint_fingerprint=profile.fingerprint,
                model_requested=profile.model,
                content='{"ok":true}',
                usage=ProviderUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
                reasoning_content="private reasoning",
            )

    service = AIProviderExecutionService(provenance.repository, Client(), root)
    service.execute(context, messages)
    result = provenance.get_attempt(context.attempt_id)
    assert result.status == status
    if unknown:
        assert result.failure_code == "PROVIDER_RESULT_UNKNOWN"
    with pytest.raises(ValueError):
        service.execute(context, messages)
    assert len(calls) == 1
    usages = provenance.list_usage(result.run_id)
    assert len(usages) == 1
    assert usages[0].prompt_tokens == (None if failure else 10)
    if unknown:
        assert usages[0].estimated_cost is None
        assert service.charged_budget(result.run_id) > 0
    assert all("private reasoning" not in p.read_text() for p in root.rglob("*.json"))
    with Session(provenance.repository.engine) as session:
        assert session.scalar(select(AIValidationResultModel)) is None


def test_missing_usage_retains_reservation_and_new_attempt_counts(execution_context):
    from dataclasses import replace

    from quant_lab.ai.provider_execution import AIProviderExecutionService
    from quant_lab.ai_provider_protocol import ProviderCallResult

    service, profile, context, messages, root = execution_context

    class Client:
        def complete(self, request, policy=None):
            return ProviderCallResult(
                request_id=request.request_id,
                endpoint_fingerprint=profile.fingerprint,
                model_requested=profile.model,
                content="ok",
            )

    execution = AIProviderExecutionService(service.repository, Client(), root)
    first = execution.execute(context, messages)
    reserve = execution.charged_budget(first.run_id)
    assert reserve > 0
    assert service.list_usage(first.run_id)[0].estimated_cost is None
    second = service.start_attempt(first.run_id, "a" * 64)
    execution.execute(replace(context, attempt_id=second.id), messages)
    assert execution.charged_budget(first.run_id) == reserve * 2
    third = service.start_attempt(first.run_id, "a" * 64)
    execution.execute(replace(context, attempt_id=third.id), messages)
    fourth = service.start_attempt(first.run_id, "a" * 64)
    with pytest.raises(ValueError, match="AI_BUDGET_EXCEEDED"):
        execution.execute(replace(context, attempt_id=fourth.id), messages)


@pytest.mark.parametrize("change", ["gate", "pack", "prompt"])
def test_invalid_authorization_blocked_before_host(execution_context, change):
    from dataclasses import replace

    from quant_lab.ai.provider_execution import AIProviderExecutionService
    from quant_lab.ai_provider_protocol import ProviderMessage

    service, _, context, messages, root = execution_context

    class Client:
        def complete(self, request, policy=None):
            pytest.fail("must not call provider")

    if change == "gate":
        context = replace(context, gate_decision="REJECT")
    elif change == "pack":
        context = replace(context, evidence_pack_fingerprint="0" * 64)
    else:
        messages = [ProviderMessage(role="user", content="changed")]
    with pytest.raises(ValueError):
        AIProviderExecutionService(service.repository, Client(), root).execute(context, messages)
    assert service.list_usage(service.get_attempt(context.attempt_id).run_id) == ()


def test_crash_after_reservation_recovers_without_retry(execution_context):
    import sqlite3

    from sqlalchemy import create_engine

    from quant_lab.ai.provenance import AIProvenanceService
    from quant_lab.ai.provider_execution import AIProviderExecutionService
    from quant_lab.ai.repository import AIRepository

    service, _, context, messages, root = execution_context

    class CrashingClient:
        def complete(self, request, policy=None):
            raise KeyboardInterrupt()

    execution = AIProviderExecutionService(service.repository, CrashingClient(), root)
    with pytest.raises(KeyboardInterrupt):
        execution.execute(context, messages)
    run_id = service.get_attempt(context.attempt_id).run_id
    before = execution.charged_budget(run_id)
    assert before > 0
    target = root / "restart.db"
    raw = service.repository.engine.raw_connection()
    with sqlite3.connect(target) as destination:
        raw.driver_connection.backup(destination)
    raw.close()
    engine = create_engine(f"sqlite+pysqlite:///{target}")
    recovered = AIProvenanceService(AIRepository(engine))
    recovered.recover_incomplete_runs(datetime.now(UTC))
    assert recovered.get_attempt(context.attempt_id).status == "ABANDONED"
    usages = recovered.list_usage(run_id)
    assert len(usages) == 1 and usages[0].prompt_tokens is None
    restart_execution = AIProviderExecutionService(recovered.repository, CrashingClient(), root)
    assert restart_execution.charged_budget(run_id) == before
    with pytest.raises(ValueError):
        restart_execution.execute(context, messages)
    engine.dispose()


def test_frozen_policy_limits_response_and_reaches_client(provenance, tmp_path):
    from quant_lab.ai.provider_execution import AIProviderExecutionService
    from quant_lab.ai_provider_protocol import CallPolicy, ProviderCallResult

    policy = CallPolicy(max_response_bytes=128, read_timeout=7)
    context = make_execution_context(provenance, tmp_path, call_policy=policy)
    _, profile, authorized, messages, root = context
    observed = []

    class Client:
        def complete(self, request, policy=None):
            observed.append(policy)
            return ProviderCallResult(
                request_id=request.request_id,
                endpoint_fingerprint=profile.fingerprint,
                model_requested=profile.model,
                content="x" * 500,
            )

    result = AIProviderExecutionService(provenance.repository, Client(), root).execute(
        authorized, messages
    )
    assert result.status == "FAILED" and result.failure_code == "PROVIDER_RESPONSE_TOO_LARGE"
    assert observed == [policy]
